use crate::{config::AuthConfig, error::ApiError};
use axum::http::{HeaderMap, StatusCode};
use futures_util::StreamExt;
use jsonwebtoken::{
    Algorithm, DecodingKey, Validation, decode, decode_header,
    jwk::{AlgorithmParameters, JwkSet},
};
use serde::{Deserialize, Serialize};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::{Mutex, RwLock, Semaphore};
use uuid::Uuid;

pub const MAX_AUTH_JSON: usize = 64 * 1024;

pub async fn bounded_bytes(response: reqwest::Response, max: usize) -> Result<Vec<u8>, ()> {
    if response.content_length().is_some_and(|n| n > max as u64) {
        return Err(());
    }
    let mut data = Vec::new();
    let mut stream = response.bytes_stream();
    while let Some(part) = stream.next().await {
        let part = part.map_err(|_| ())?;
        if part.len() > max.saturating_sub(data.len()) {
            return Err(());
        }
        data.extend_from_slice(&part);
    }
    Ok(data)
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Account {
    pub user_id: Uuid,
    pub client_id: String,
    pub ocr_id: String,
    pub daily_limit: u32,
    pub rate_per_minute: u32,
    pub used_today: u32,
}
#[derive(Clone, Deserialize)]
pub struct Claims {
    pub sub: Uuid,
    pub session_id: Uuid,
    pub exp: u64,
}

struct KeyCache {
    keys: JwkSet,
    loaded: Instant,
}
pub struct Auth {
    config: AuthConfig,
    http: reqwest::Client,
    keys: RwLock<Option<KeyCache>>,
    refresh: Mutex<Option<Instant>>,
    database_slots: Semaphore,
}
#[derive(Clone)]
pub struct Identity {
    pub token: Arc<str>,
    pub claims: Claims,
    pub account: Account,
}

impl Auth {
    pub fn new(config: AuthConfig) -> Result<Self, reqwest::Error> {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .connect_timeout(Duration::from_secs(2))
            .redirect(reqwest::redirect::Policy::none())
            .pool_max_idle_per_host(config.database_concurrency)
            .build()?;
        Ok(Self {
            database_slots: Semaphore::new(config.database_concurrency),
            config,
            http,
            keys: RwLock::new(None),
            refresh: Mutex::new(None),
        })
    }
    pub async fn authenticate(&self, headers: &HeaderMap) -> Result<Identity, ApiError> {
        let token = headers
            .get("authorization")
            .and_then(|s| s.to_str().ok())
            .and_then(|s| s.strip_prefix("Bearer "))
            .filter(|s| (20..=8192).contains(&s.len()))
            .ok_or_else(ApiError::unauthorized)?;
        self.authenticate_token(Arc::from(token)).await
    }
    pub async fn authenticate_token(&self, token: Arc<str>) -> Result<Identity, ApiError> {
        let header = decode_header(token.as_ref()).map_err(|_| ApiError::unauthorized())?;
        if header.alg != Algorithm::ES256 {
            return Err(ApiError::unauthorized());
        }
        let kid = header
            .kid
            .as_deref()
            .filter(|s| s.len() <= 128)
            .ok_or_else(ApiError::unauthorized)?;
        let key = self.key(kid).await?;
        let claims = validate_token(&token, &key, &self.config.supabase_url)?;
        let _slot = tokio::time::timeout(Duration::from_millis(500), self.database_slots.acquire())
            .await
            .map_err(|_| ApiError::busy("auth_capacity"))?
            .map_err(|_| ApiError::unavailable("auth_unavailable"))?;
        // Same user JWT on the RPC: revoked sessions, ban and Google provider are checked in Postgres.
        // No service-role key, client-supplied userId or cached authorization decision.
        let response = self
            .http
            .post(format!(
                "{}/rest/v1/rpc/ocr_gateway_session",
                self.config.supabase_url.trim_end_matches('/')
            ))
            .header("apikey", &self.config.publishable_key)
            .bearer_auth(token.as_ref())
            .json(&serde_json::json!({"p_session_id": claims.session_id}))
            .send()
            .await
            .map_err(|_| ApiError::unavailable("identity_database_unavailable"))?;
        match response.status().as_u16() {
            401 => return Err(ApiError::unauthorized()),
            403 => {
                return Err(ApiError::new(
                    StatusCode::FORBIDDEN,
                    "account_or_session_disabled",
                ));
            }
            200 => (),
            _ => return Err(ApiError::unavailable("identity_database_unavailable")),
        }
        let data = bounded_bytes(response, MAX_AUTH_JSON)
            .await
            .map_err(|_| ApiError::unavailable("identity_response_invalid"))?;
        let account: Account = serde_json::from_slice(&data)
            .map_err(|_| ApiError::unavailable("identity_response_invalid"))?;
        if account.user_id != claims.sub
            || !(1..=500).contains(&account.daily_limit)
            || !(1..=30).contains(&account.rate_per_minute)
        {
            return Err(ApiError::unavailable("identity_policy_mismatch"));
        }
        Ok(Identity {
            token,
            claims,
            account,
        })
    }
    async fn key(&self, kid: &str) -> Result<DecodingKey, ApiError> {
        if let Some(key) = self.cached_key(kid).await {
            return Ok(key);
        }
        let mut last_attempt = self.refresh.lock().await;
        if let Some(key) = self.cached_key(kid).await {
            return Ok(key);
        }
        // Unknown kid floods cannot stampede JWKS or cause one HTTP request per invalid JWT.
        if last_attempt.is_some_and(|t| t.elapsed() < Duration::from_secs(30)) {
            return Err(ApiError::unauthorized());
        }
        *last_attempt = Some(Instant::now());
        let response = self
            .http
            .get(format!(
                "{}/auth/v1/.well-known/jwks.json",
                self.config.supabase_url.trim_end_matches('/')
            ))
            .send()
            .await
            .map_err(|_| ApiError::unavailable("jwks_unavailable"))?;
        if !response.status().is_success() {
            return Err(ApiError::unavailable("jwks_unavailable"));
        }
        let data = bounded_bytes(response, MAX_AUTH_JSON)
            .await
            .map_err(|_| ApiError::unavailable("jwks_invalid"))?;
        let keys: JwkSet =
            serde_json::from_slice(&data).map_err(|_| ApiError::unavailable("jwks_invalid"))?;
        if keys.keys.len() > 16 {
            return Err(ApiError::unavailable("jwks_invalid"));
        }
        *self.keys.write().await = Some(KeyCache {
            keys,
            loaded: Instant::now(),
        });
        self.cached_key(kid)
            .await
            .ok_or_else(ApiError::unauthorized)
    }
    async fn cached_key(&self, kid: &str) -> Option<DecodingKey> {
        let cache = self.keys.read().await;
        let cache = cache
            .as_ref()
            .filter(|c| c.loaded.elapsed() < Duration::from_secs(300))?;
        let jwk = cache.keys.find(kid)?;
        if !matches!(jwk.algorithm, AlgorithmParameters::EllipticCurve(_)) {
            return None;
        }
        DecodingKey::from_jwk(jwk).ok()
    }
}

fn validate_token(token: &str, key: &DecodingKey, origin: &str) -> Result<Claims, ApiError> {
    let mut v = Validation::new(Algorithm::ES256);
    v.set_issuer(&[format!("{}/auth/v1", origin.trim_end_matches('/'))]);
    v.set_audience(&["authenticated"]);
    v.set_required_spec_claims(&["exp", "iss", "aud", "sub"]);
    v.leeway = 5;
    v.validate_nbf = true;
    let claims = decode::<Claims>(token, key, &v)
        .map_err(|_| ApiError::unauthorized())?
        .claims;
    if claims.sub.is_nil() || claims.session_id.is_nil() {
        return Err(ApiError::unauthorized());
    }
    Ok(claims)
}

#[cfg(test)]
mod tests {
    use super::*;
    use jsonwebtoken::{EncodingKey, Header, encode};
    use ring::{
        rand::SystemRandom,
        signature::{ECDSA_P256_SHA256_FIXED_SIGNING, EcdsaKeyPair, KeyPair},
    };

    #[test]
    fn signed_google_access_token_requires_correct_signature_issuer_audience_session_and_time() {
        let random = SystemRandom::new();
        let private =
            EcdsaKeyPair::generate_pkcs8(&ECDSA_P256_SHA256_FIXED_SIGNING, &random).unwrap();
        let pair =
            EcdsaKeyPair::from_pkcs8(&ECDSA_P256_SHA256_FIXED_SIGNING, private.as_ref(), &random)
                .unwrap();
        let public = pair.public_key().as_ref();
        use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
        let key = DecodingKey::from_ec_components(
            &URL_SAFE_NO_PAD.encode(&public[1..33]),
            &URL_SAFE_NO_PAD.encode(&public[33..]),
        )
        .unwrap();
        let origin = "https://rrdxhztiikizgogxtlhu.supabase.co";
        let now = crate::camera::unix_ms() / 1000;
        let valid = serde_json::json!({ "sub": Uuid::new_v4(), "session_id": Uuid::new_v4(),
            "exp": now + 300, "iss": format!("{origin}/auth/v1"), "aud": "authenticated", "nbf": now - 1 });
        let sign = |claims: &serde_json::Value| {
            encode(
                &Header::new(Algorithm::ES256),
                claims,
                &EncodingKey::from_ec_der(private.as_ref()),
            )
            .unwrap()
        };
        assert!(validate_token(&sign(&valid), &key, origin).is_ok());
        for (field, value) in [
            ("exp", serde_json::json!(now - 120)),
            ("nbf", serde_json::json!(now + 120)),
            (
                "iss",
                serde_json::json!("https://different.supabase.co/auth/v1"),
            ),
            ("aud", serde_json::json!("other")),
            ("session_id", serde_json::Value::Null),
            ("sub", serde_json::json!(Uuid::nil())),
        ] {
            let mut invalid = valid.clone();
            invalid[field] = value;
            assert!(
                validate_token(&sign(&invalid), &key, origin).is_err(),
                "accepted invalid {field}"
            );
        }
        let hmac = encode(
            &Header::new(Algorithm::HS256),
            &valid,
            &EncodingKey::from_secret(b"not-a-signing-key").unwrap(),
        )
        .unwrap();
        assert!(validate_token(&hmac, &key, origin).is_err());
        let wrong = DecodingKey::from_ec_der(&[0; 65]);
        assert!(validate_token(&sign(&valid), &wrong, origin).is_err());
    }
}
