use hmac::{Hmac, Mac};
use sha2::Sha256;
use subtle::ConstantTimeEq;

const REPLAY_WINDOW_SECS: i64 = 60 * 5;

#[derive(Debug, PartialEq)]
pub enum SigError {
    BadFormat,
    Expired,
    Mismatch,
}

pub fn verify_slack_signature(
    signing_secret: &str,
    timestamp_header: &str,
    signature_header: &str,
    body: &[u8],
    now_unix: i64,
) -> Result<(), SigError> {
    let ts: i64 = timestamp_header.parse().map_err(|_| SigError::BadFormat)?;
    if (now_unix - ts).abs() > REPLAY_WINDOW_SECS {
        return Err(SigError::Expired);
    }

    let expected = signature_header
        .strip_prefix("v0=")
        .ok_or(SigError::BadFormat)?;
    let expected_bytes = hex::decode(expected).map_err(|_| SigError::BadFormat)?;

    let basestring = format!("v0:{}:", timestamp_header);
    let mut mac = Hmac::<Sha256>::new_from_slice(signing_secret.as_bytes())
        .map_err(|_| SigError::BadFormat)?;
    mac.update(basestring.as_bytes());
    mac.update(body);
    let computed = mac.finalize().into_bytes();

    if computed.ct_eq(&expected_bytes).into() {
        Ok(())
    } else {
        Err(SigError::Mismatch)
    }
}

use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::Serialize;
use std::env;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Serialize)]
struct WorkItem {
    channel_id: String,
    thread_ts: String,
    processing_ts: Option<String>,
}

async fn handler(
    sqs: &aws_sdk_sqs::Client,
    queue_url: &str,
    signing_secret: &str,
    req: Request,
) -> Result<Response<Body>, Error> {
    let ts = req
        .headers()
        .get("x-slack-request-timestamp")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    let sig = req
        .headers()
        .get("x-slack-signature")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let body_bytes = req.body().to_vec();
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() as i64;

    if verify_slack_signature(signing_secret, ts, sig, &body_bytes, now).is_err() {
        return Ok(Response::builder().status(401).body("invalid signature".into())?);
    }

    let body_str = std::str::from_utf8(&body_bytes)
        .map_err(|_| Error::from("non-utf8 body"))?;
    let parsed = url::form_urlencoded::parse(body_str.as_bytes());
    let mut payload_str: Option<String> = None;
    for (k, v) in parsed {
        if k == "payload" {
            payload_str = Some(v.to_string());
            break;
        }
    }
    let Some(payload_str) = payload_str else {
        return Ok(Response::builder().status(400).body("missing payload".into())?);
    };

    let payload: serde_json::Value = serde_json::from_str(&payload_str)
        .map_err(|_| Error::from("invalid payload json"))?;

    if payload.get("type").and_then(|v| v.as_str()) != Some("message_action") {
        return Ok(Response::builder().status(200).body("".into())?);
    }

    let channel_id = payload
        .pointer("/channel/id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| Error::from("missing channel.id"))?
        .to_string();
    let thread_ts = payload
        .pointer("/message/ts")
        .and_then(|v| v.as_str())
        .ok_or_else(|| Error::from("missing message.ts"))?
        .to_string();

    let item = WorkItem { channel_id, thread_ts, processing_ts: None };
    let body = serde_json::to_string(&item)?;

    sqs.send_message().queue_url(queue_url).message_body(body).send().await
        .map_err(|e| Error::from(format!("sqs send failed: {e}")))?;

    Ok(Response::builder().status(200).body("".into())?)
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt().json().with_target(false).without_time().init();

    let queue_url = env::var("SQS_QUEUE_URL").expect("SQS_QUEUE_URL");

    let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
    let sqs = aws_sdk_sqs::Client::new(&config);

    let signing_secret = if let Ok(direct) = env::var("SLACK_SIGNING_SECRET") {
        direct
    } else {
        let param_name = env::var("SLACK_SIGNING_SECRET_PARAM").expect("SLACK_SIGNING_SECRET or SLACK_SIGNING_SECRET_PARAM");
        let ssm = aws_sdk_ssm::Client::new(&config);
        ssm.get_parameter().name(param_name).with_decryption(true).send().await?
            .parameter().and_then(|p| p.value()).ok_or_else(|| Error::from("ssm value missing"))?.to_string()
    };

    run(service_fn(|req| handler(&sqs, &queue_url, &signing_secret, req))).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use hmac::Mac;

    fn make_sig(secret: &str, ts: &str, body: &[u8]) -> String {
        let basestring = format!("v0:{}:", ts);
        let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).unwrap();
        mac.update(basestring.as_bytes());
        mac.update(body);
        format!("v0={}", hex::encode(mac.finalize().into_bytes()))
    }

    #[test]
    fn valid_signature_succeeds() {
        let secret = "shh";
        let ts = "1700000000";
        let body = b"payload=abc";
        let sig = make_sig(secret, ts, body);
        assert!(verify_slack_signature(secret, ts, &sig, body, 1700000010).is_ok());
    }

    #[test]
    fn expired_signature_rejected() {
        let secret = "shh";
        let ts = "1700000000";
        let body = b"payload=abc";
        let sig = make_sig(secret, ts, body);
        let now = 1700000000 + REPLAY_WINDOW_SECS + 1;
        assert_eq!(
            verify_slack_signature(secret, ts, &sig, body, now),
            Err(SigError::Expired)
        );
    }

    #[test]
    fn tampered_body_rejected() {
        let secret = "shh";
        let ts = "1700000000";
        let sig = make_sig(secret, ts, b"original");
        assert_eq!(
            verify_slack_signature(secret, ts, &sig, b"tampered", 1700000010),
            Err(SigError::Mismatch)
        );
    }

    #[test]
    fn bad_prefix_rejected() {
        assert_eq!(
            verify_slack_signature("shh", "1700000000", "v1=abcd", b"x", 1700000010),
            Err(SigError::BadFormat)
        );
    }

    #[test]
    fn non_numeric_timestamp_rejected() {
        assert_eq!(
            verify_slack_signature("shh", "abc", "v0=abcd", b"x", 1700000010),
            Err(SigError::BadFormat)
        );
    }
}
