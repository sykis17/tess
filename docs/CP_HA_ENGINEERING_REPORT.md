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

The control plane's authority is an etcd lease. One node holds the lease and is
primary; if it stops renewing, the lease expires and the standby can acquire it.
Leadership by itself does not order writes, so each time a node wins the lease it
also mints a *fence term*: an integer, held in etcd, that advances by one on every
acquisition. That ordering is constructed by the design, not handed down by etcd.
The increment is itself a compare-and-swap — etcd installs the next value only if
the stored one has not changed — so two nodes racing to promote cannot both claim
the same term, and the value only ever moves up; the term is then mirrored into
Redis under a promotion that accepts it only when it is strictly higher than the
one already stored. etcd supplies the lease and the atomic transaction; the fence
term's monotonicity is built on top of them. Because the term is ordered, a writer
can prove it is newer than another by holding a higher number — and a holder of a
lower number can be recognized, and rejected, as stale.

That ordering is what closes the gap §1 described. A primary does not check the
lease and then issue an unconditional write; it carries its fence term into the
write and conditions the write on that term still being current. The durable
write to `ops:control_plane` is a Redis Lua script that sets the blob only if the
fence term stored in Redis still equals the writer's term (`persist_store`
running the `_LUA_PERSIST_CAS` compare-and-swap). Inside that script the term
check and the blob write are one atomic step, with no window between them. The
etcd check and the Redis write, by contrast, stay two separate steps with a real
gap between them — but the commit is decided only at the second. etcd decides who
is *allowed* to attempt a write; the Redis compare-and-swap decides who actually
*commits* one. A zombie that clears the first lock — because it has not yet noticed
its lease is gone — is stopped at the second, by Redis itself, on the strength of a
term it can no longer match.

A rejected write is inert unless the rejected node does something about it. A
compare-and-swap failure here is not a transient error to retry; it is positive
evidence that another primary exists with a newer term — which means this node is
the zombie. The design therefore gives a Redis CAS rejection the same severity as
an etcd rejection: the in-memory mutation is rolled back, the node demotes itself,
and the error is raised, never downgraded to a warning (`FenceCasError`, handled
by restore-then-demote-then-raise). That parity is what makes the second lock
trustworthy. Rejecting the write protects the data; demoting the writer protects
the *system*, by ensuring a fenced node stops believing it is primary instead of
looping on a write it will never land.

Two locks and a stand-down rule cover a node that writes directly, but not every
writer is a request-handling web process. Heavy ops work runs on Celery workers,
and a task can be enqueued while its node is primary and executed moments after
that node has lost the lease. A cached role, correct at enqueue time, is exactly
the stale authority the design exists to reject. So worker ops tasks are required
to perform a fresh etcd leader-and-term check at the moment they run
(`check_fence_live`), never a cached role value — and this is enforced
structurally, not by convention: a test greps the worker source and fails if a
task reads the cached-role helpers at all. The fresh check is the same fence,
applied at the one place — deferred execution — where cached authority would
otherwise slip through.

The last enforcement point is the HTTP surface. Mutating `/ops/*` endpoints are
gated *before* per-endpoint admin authentication: on a standby, the request is
refused with a 503 and the fence body regardless of whether the caller's
credentials are valid. Ordering the fence ahead of auth guarantees that a stale
or standby node cannot mutate control-plane state even when presented with correct
admin tokens, and it keeps the refusal uniform across every mutation endpoint. The
order carries a deliberate cost, recorded as a contract rather than met as a
surprise: because the fence answers before auth, an unauthenticated caller can
learn which node is primary from a mutation endpoint's response. Reads and the
`/ops/ha` status endpoint stay available on both nodes; only mutations are fenced.

Each of these mechanisms — an ordered lease, a write-time compare-and-swap, a
stand-down rule of equal severity, a fresh authority check for deferred worker
execution, and a fence-before-auth HTTP gate — closes a gap the previous one
leaves open. What none of them provides is evidence that they hold under the
failures they are meant to survive: a frozen process rather than a clean crash, a
partition rather than a stop, deferred execution under a prefork worker, a
byte-encoded header, an air-gapped network. Producing that evidence is a separate
task from stating the design, and it is the subject of the rest of this report.

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
