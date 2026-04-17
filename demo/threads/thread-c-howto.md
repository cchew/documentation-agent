# Thread C — How-To: Rotating AWS RDS credentials without downtime

**Channel:** #platform-eng
**Date:** 2026-03-21

---

[14:05] @priya.sharma: working through the quarterly credential rotation for RDS. documenting what I'm doing as I go in case anyone needs this later
[14:06] @priya.sharma: step 1: go to AWS Secrets Manager → select the RDS secret (ours is `/prod/rds/api-db`) → choose "Rotate secret immediately"
[14:10] @priya.sharma: step 2: confirm the rotation Lambda is configured — if it's not set up you'll get an error. ours uses the `SecretsManagerRDSMySQLRotationSingleUser` Lambda
[14:13] @dan.okoye: heads up — if you're on multi-user rotation, the Lambda name is different: `SecretsManagerRDSMySQLRotationMultiUser`. we switched to multi-user last quarter
[14:14] @priya.sharma: good catch @dan.okoye — updating: we are on multi-user. using `SecretsManagerRDSMySQLRotationMultiUser`
[14:18] @priya.sharma: step 3: trigger rotation. watch CloudWatch logs for the Lambda — it'll create a new password, update it in RDS, then update the secret value
[14:26] @priya.sharma: step 4: verify apps are picking up the new secret. our apps use the AWS SDK to fetch the secret at startup, so I'm doing a rolling restart of the API fleet now
[14:34] @priya.sharma: step 5: confirm — check app logs for any DB auth errors after restart. watching now
[14:40] @priya.sharma: all clear, no auth errors. apps reconnected cleanly
[14:42] @dan.okoye: what's the window where you'd see errors if something went wrong?
[14:44] @priya.sharma: roughly between triggering rotation and completing the rolling restart — maybe 5–8 min. if you see DB auth errors in that window, the rotation Lambda likely failed. check CloudWatch first
[14:47] @maya.chen: how often do we need to do this?
[14:48] @priya.sharma: quarterly for compliance. Secrets Manager can do it automatically but we keep it manual so we control the restart timing
[14:51] @priya.sharma: full runbook: (1) Secrets Manager rotate → (2) confirm Lambda type → (3) watch CloudWatch → (4) rolling restart → (5) verify logs. ~45 min total including buffer
