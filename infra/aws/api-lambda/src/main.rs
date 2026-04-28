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

fn main() {
    println!("api-lambda — handler not yet wired");
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
