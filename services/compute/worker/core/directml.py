"""Server-only DirectML adapter for the verified ML_s44 FP32 export."""
import hashlib,json,math
from pathlib import Path
import numpy as np
from PIL import Image
from .recognizer import prepare_image,normalize

class DirectMLRecognizer:
    def __init__(self,model_dir,index,threads=2):
        import onnxruntime as ort
        if 'DmlExecutionProvider' not in ort.get_available_providers():raise ValueError('DirectML runtime unavailable')
        # Native DXGI probing stays in the disposable discovery process. Do not
        # create unrelated D3D12 devices inside a loaded model process.
        folder=Path(model_dir)/'onnx'
        self.manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        config=json.loads((Path(model_dir)/'model_config.json').read_text(encoding='utf-8'))
        m=self.manifest
        if m['source_sha256']!=config['weights_sha256'] or m['precision']!='FP32' or m['preprocessing']!='v2c':
            raise ValueError('DirectML export does not match the selected model')
        self.sessions=[]
        for name in ('encoder','decoder'):
            row=m['models'][name];path=(folder/row['file']).resolve()
            if path.parent!=folder.resolve():raise ValueError('Invalid ONNX path')
            with path.open('rb') as handle:
                if hashlib.file_digest(handle,'sha256').hexdigest()!=row['sha256']:raise ValueError('ONNX hash mismatch')
            options=ort.SessionOptions();options.enable_mem_pattern=False
            options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
            options.intra_op_num_threads=threads;options.inter_op_num_threads=1
            options.add_session_config_entry('session.intra_op.allow_spinning','0')
            session=ort.InferenceSession(str(path),sess_options=options,
                providers=[('DmlExecutionProvider',{'device_id':str(index)}),'CPUExecutionProvider'])
            session.disable_fallback()
            if session.get_providers()[0]!='DmlExecutionProvider':raise ValueError('DirectML failed to activate')
            self.sessions.append(session)
    def warmup(self):
        m=self.manifest
        memory=self.sessions[0].run(None,{'image':np.zeros((1,3,m['image_height'],m['max_width']),dtype=np.float32)})[0]
        self.sessions[1].run(None,{'tokens':np.ones((8,1),dtype=np.int64),'memory':memory})
    def read(self,image,pre='v2c'):
        return self.predict(prepare_image(image.convert('RGB'),pre)[0])

    def predict(self,image):
        m=self.manifest
        width=math.ceil(int(m['image_height']*float(image.width)/float(image.height))/10)*10
        width=max(m['min_width'],min(m['max_width'],width))
        image=image.resize((width,m['image_height']),Image.Resampling.LANCZOS)
        tensor=np.ascontiguousarray((np.asarray(image).transpose(2,0,1)/255).astype(np.float32)[None])
        memory=self.sessions[0].run(None,{'image':tensor})[0];tokens=[m['sos']]
        for _ in range(m['max_tokens']):
            _,prediction=self.sessions[1].run(None,{'tokens':np.asarray(tokens,dtype=np.int64)[:,None],'memory':memory})
            token=int(prediction[0])
            if token==m['eos']:break
            tokens.append(token)
        return normalize(''.join(m['vocabulary'][t] for t in tokens[1:]))
