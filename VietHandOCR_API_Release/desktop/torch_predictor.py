"""VietOCR-compatible inference without random VGG classifier allocation.

The model and checkpoint keys are the upstream architecture. Meta construction
skips allocating/initializing the VGG classifier that the backbone discards.
Greedy decoding keeps the prefix on the device and transfers only one token.
"""
from copy import deepcopy
import logging
import time

logger = logging.getLogger('vietocr_desktop.ocr')


class TorchPredictor:
    def __init__(self, config):
        import torch
        from vietocr.tool.translate import build_model
        self.config = deepcopy(config)
        self.device = config['device']
        construction = deepcopy(config)
        construction['device'] = 'meta'
        construction['cnn']['pretrained'] = False
        started = time.perf_counter()
        with torch.device('meta'):
            self.model, self.vocab = build_model(construction)
        weights = config['weights']
        try:
            state = torch.load(weights, map_location='cpu', weights_only=True, mmap=True)
        except RuntimeError as error:
            if 'mmap' not in str(error): raise
            state = torch.load(weights, map_location='cpu', weights_only=True)
        # Compact checkpoints store FP16 but the original network computes FP32.
        state = {name: value.float() if value.is_floating_point() and value.dtype != torch.float32 else value
                 for name, value in state.items()}
        self.model.load_state_dict(state, strict=True, assign=True)
        del state
        self.model.to(self.device).eval().requires_grad_(False)
        logger.info('Torch model initialized in %.3fs (meta, FP32 compute, %s)', time.perf_counter()-started, self.device)

    def predict(self, image, return_prob=False):
        import torch
        from vietocr.tool.translate import process_input, translate_beam_search
        dataset = self.config['dataset']
        image = process_input(image, dataset['image_height'], dataset['image_min_width'], dataset['image_max_width']).to(self.device)
        with torch.inference_mode():
            if self.config['predictor'].get('beamsearch'):
                text = self.vocab.decode(translate_beam_search(image, self.model))
                return (text, None) if return_prob else text
            memory = self.model.transformer.forward_encoder(self.model.cnn(image))
            language = self.model.transformer
            caches = [None] * len(language.transformer.decoder.layers)
            cross = [self._project_memory(layer.multihead_attn, memory) for layer in language.transformer.decoder.layers]
            token_tensor = torch.ones((1, 1), dtype=torch.long, device=self.device)
            decoded, probabilities = [1], []
            for step in range(129):
                x = language.embed_tgt(token_tensor) * (language.d_model ** .5)
                x = x + language.pos_enc.pe[step:step+1]
                for index, layer in enumerate(language.transformer.decoder.layers):
                    attended, caches[index] = self._self_attention(layer.self_attn, x, caches[index])
                    x = layer.norm1(x + attended)
                    x = layer.norm2(x + self._cross_attention(layer.multihead_attn, x, cross[index]))
                    x = layer.norm3(x + layer.linear2(layer.activation(layer.linear1(x))))
                last = language.fc(language.transformer.decoder.norm(x)[0])
                # softmax preserves ranking; no full sequence/vocabulary CPU copy.
                next_id = last.argmax(-1)
                token_tensor = next_id.view(1, 1)
                token = int(next_id.item())
                decoded.append(token)
                if return_prob and token > 3:
                    probabilities.append(float(last.softmax(-1).max().item()))
                if token == 2: break
            text = self.vocab.decode(decoded)
            return (text, sum(probabilities) / max(1, len(probabilities))) if return_prob else text

    @staticmethod
    def _heads(value, heads):
        return value.view(value.shape[0], value.shape[1], heads, value.shape[2] // heads).permute(1, 2, 0, 3)

    @classmethod
    def _project_memory(cls, attention, memory):
        import torch.nn.functional as functional
        dim = attention.embed_dim
        key, value = functional.linear(memory, attention.in_proj_weight[dim:], attention.in_proj_bias[dim:]).chunk(2, -1)
        return cls._heads(key, attention.num_heads), cls._heads(value, attention.num_heads)

    @classmethod
    def _attend(cls, attention, query, key, value):
        import torch.nn.functional as functional
        out = functional.scaled_dot_product_attention(cls._heads(query, attention.num_heads), key, value, dropout_p=0)
        out = out.permute(2, 0, 1, 3).reshape(query.shape[0], query.shape[1], attention.embed_dim)
        return attention.out_proj(out)

    @classmethod
    def _self_attention(cls, attention, x, cache):
        import torch
        import torch.nn.functional as functional
        query, key, value = functional.linear(x, attention.in_proj_weight, attention.in_proj_bias).chunk(3, -1)
        key, value = cls._heads(key, attention.num_heads), cls._heads(value, attention.num_heads)
        if cache is not None:
            key, value = torch.cat((cache[0], key), dim=2), torch.cat((cache[1], value), dim=2)
        return cls._attend(attention, query, key, value), (key, value)

    @classmethod
    def _cross_attention(cls, attention, x, cache):
        import torch.nn.functional as functional
        dim = attention.embed_dim
        query = functional.linear(x, attention.in_proj_weight[:dim], attention.in_proj_bias[:dim])
        return cls._attend(attention, query, cache[0], cache[1])

    def predict_batch(self, images, return_prob=False):
        values = [self.predict(image, return_prob=return_prob) for image in images]
        if return_prob:
            return [row[0] for row in values], [row[1] for row in values]
        return values
