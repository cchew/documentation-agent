# Thread B — Q&A: How to configure feature flags in the staging environment

**Channel:** #platform-eng
**Date:** 2026-03-20

---

[10:15] @james.liu: quick q — how do we enable a feature flag for staging only? I need to test the new smart search behind a flag but can't find where to configure it in AppConfig
[10:18] @sarah.obi: we use AWS AppConfig for feature flags. open the AppConfig console, find the app, then look under the Environments tab for the right environment
[10:19] @james.liu: I can see the app but there's no "staging" environment listed, only prod and dev
[10:22] @sarah.obi: oh right — staging was renamed to "pre-prod" about 3 months ago when we reorganised the environments. it's a bit confusing
[10:24] @james.liu: found it. do I just edit the flag value in the config profile and redeploy, or is there something else?
[10:27] @sarah.obi: correct — open the Feature Flag config profile for pre-prod, set `smart-search-v2` to enabled, save a new version, then start a new deployment. use the AllAtOnce deployment strategy for internal testing
[10:29] @tom.walsh: also double-check the environment selector before you hit deploy — AppConfig will let you deploy to prod if you're not careful. no guard rails there
[10:31] @james.liu: what's the fastest rollback if something goes wrong in pre-prod?
[10:33] @sarah.obi: in the AppConfig deployment view there's a "Stop deployment and roll back" button while it's in progress. once complete, you'd flip the flag back to disabled, save a new version, and redeploy. rollback button is faster if you catch it early
[10:34] @james.liu: makes sense. actually I can't deploy at all — getting an access denied on StartDeployment
[10:36] @sarah.obi: you need the `appconfig:StartDeployment` IAM permission scoped to the pre-prod environment. I'll add you to the platform-eng-deployers group now
[10:37] @james.liu: got it — access is working. `smart-search-v2` flag is live in pre-prod, testing now
[10:52] @james.liu: all working. thanks @sarah.obi and @tom.walsh
[10:54] @sarah.obi: we should really add this to the platform docs — this comes up every time someone creates a new flag
[10:55] @tom.walsh: +1, happy to review a doc if someone writes it
