# High-Availability Control Plane: Design and Verification

*An engineering report on the control plane that decides which cloud provider
serves TESS Engine's traffic — what it guards, how it was designed to fail
safely, and the layered verification that found six defects before any of them
could reach production. Written to be checked: every factual claim traces to a
commit, test, file, or captured artifact, and every claim about how a defect was
discovered is labeled either re-demonstrable from the repository or attested by
the author.*

---

## 1. Context and problem

TESS Engine can serve its workload from more than one place. The default is a
host on Hetzner; AWS, GCP, or a customer's own infrastructure can be registered
as alternates. Deciding which of these is *live* — which provider currently
receives traffic — is the job of a dedicated ops control plane. It holds three things
that matter: the routing decision (`active_provider_id`, the provider serving
right now), a registry of the known providers and their health, and the policy
that governs when to fail over. Operators change it through an `/ops/*` HTTP API,
and the decision is stored durably in Redis so that every web and worker process
reads the same answer.

Because that decision is load-bearing, the control plane itself is run for
availability: a primary and a standby, with leadership held through an etcd
lease. The failure that this design is really about is not a clean crash — a
process that dies releases its lease and its work stops, which is easy to handle.
The dangerous case is the *zombie*: a primary that has lost its lease — frozen,
garbage-collection-paused, or partitioned from etcd — but whose process is still
alive and still running code that writes to the shared Redis state. If that stale
primary writes the routing decision, it can point live traffic at the wrong
provider, or overwrite a decision that a newer, rightful primary has already
made. Two processes each believing they are primary, issuing conflicting routing
— split brain — is the specific catastrophe to prevent.

Concretely, the state a zombie must never write is one durable blob in Redis,
under the key `ops:control_plane`. It is the serialized control-plane store, and
its consequential contents are exactly the three things above: the active-provider
routing decision, the provider registry, and the failover policy. Anything that
could redirect traffic or contradict a newer primary lives in that blob. Guarding
it — ensuring only the one rightful primary can write it, and that a stale writer
is stopped and knows it has been stopped — is the whole problem.

Redis alone cannot solve this, because Redis has no concept of a rightful
primary. A plain last-writer-wins `SET` will faithfully accept a zombie's write.
Introducing an etcd lease gives an authority for *who should be primary*, but an
authority consulted only *before* writing is a check with a gap: between "etcd
says I am primary" and "I write to Redis," leadership can change. What the control
plane needs is both a monotonic notion of authority and enforcement at the moment
of the write itself. That pairing is the subject of the next section.

<!-- Sections below are drafted one at a time; see docs/CP_HA_REPORT_EVIDENCE.md. -->

## 2. Design

*(draft pending)*

## 3. The verification layers

*(draft pending)*

## 4. Findings

*(draft pending)*

## 5. What is and isn't proven

*(draft pending)*

## 6. Numbers appendix

*(draft pending)*

## 7. Process note

*(draft pending)*
