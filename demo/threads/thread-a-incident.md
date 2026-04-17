# Thread A — Incident: DB Connection Pool Exhaustion

**Channel:** #incidents
**Date:** 2026-03-18

---

[09:02] @priya.sharma: 🚨 getting paged — prod API response times spiking, p99 > 8s. starting to look
[09:04] @priya.sharma: DB queries timing out. Oracle UCP metrics look very wrong
[09:07] @dan.okoye: I see it too. error rate up to 12% on /api/summary. can you pull Oracle UCP pool stats?
[09:11] @priya.sharma: UCP showing pool exhausted — all 20 connections borrowed, 150 requests queued. something is holding connections open
[09:14] @tom.walsh: deployed the new summary-enrichment service at 08:45, could be related?
[09:15] @dan.okoye: almost certainly. let me check the connection handling in that service
[09:16] @priya.sharma: @tom.walsh can you roll it back while we investigate?
[09:17] @tom.walsh: rolling back now
[09:23] @tom.walsh: rollback complete, deploying v2.3.1
[09:27] @priya.sharma: UCP stats recovering. borrowed connection count dropping. p99 coming down
[09:31] @dan.okoye: found it — summary-enrichment service was opening a new Oracle connection per request inside a loop and not returning it to the pool. classic connection leak
[09:33] @priya.sharma: confirmed, error rate back to baseline. incident resolved
[09:35] @dan.okoye: root cause: missing `connection.close()` in the enrichment loop in `SummaryEnrichmentService.java` line 87. fix is in PR #442
[09:38] @tom.walsh: also bumping UCP max pool size from 20→40 as short-term buffer while PR is reviewed
[09:43] @priya.sharma: ✅ all clear. total impact: ~41 minutes, ~12% error rate on /api/summary. PR #442 is the permanent fix
[09:47] @maya.chen: sorry late to this — anything I need to document for the post-mortem?
[09:48] @priya.sharma: @maya.chen yes — the timeline is all in this thread. will tag you in the post-mortem ticket
[09:51] @priya.sharma: @tom.walsh please notify change manager jane.doe@example.com with the incident summary and rollback details for the emergency CAB record
