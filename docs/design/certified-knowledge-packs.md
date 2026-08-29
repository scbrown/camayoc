# Design: certified knowledge packs

> **Implementation status (2026-08-29):** 🟩 **Producer certification and
> digest-addressed distribution built.** Quipu implements `.qpack.db`
> creation, deterministic content hashing, verification, attach/import, and the
> `CertifiedShareBundle` SHACL envelope. Camayoc's `certify_pack.py` invokes
> pack+verify, reads the authoritative manifest hash, and emits the separate
> publisher/certifier claims plus external-truth mapping. It verifies distinct
> Ed25519 keys, computes the hash from a conforming JSON SHACL report, and scans
> the complete SQLite artifact before asserting scrub success. The RML executor
> remains a separate acceptance gate.

Camayoc has one distribution artifact, not a Camayoc pack beside a Quipu share
bundle. A Camayoc knowledge pack **is** a Quipu `CertifiedShareBundle`; its
physical archive encoding is `.qpack.db`.

## 1. Normative artifact contract

Quipu owns the bytes and their identity:

- `quipu pack` writes the `.qpack.db` SQLite artifact.
- `pack_manifest.content_hash` is the canonical graph hash: SHA-256 over the
  lexically sorted, deduplicated N-Triples of graph, shapes, stored queries,
  and labels.
- The same content hash names the artifact in git, OCI, Garage, and the graph.
  Upload location and filename are copies, never new identities.
- `quipu pack --verify` establishes integrity only. It does not establish who
  published the pack or whether its knowledge passed certification.

Camayoc owns the certification envelope. One RDF node typed
`aegis:CertifiedShareBundle` carries exactly one canonical graph hash, shapes
bundle version, provenance manifest, publisher attestation, and certification
seal. The two signatures are separate claims:

1. `aegis:PublisherAttestation` binds the publisher's registered key and
   signature to the bundle.
2. `aegis:KnowledgeCertificationSeal` binds an independent certifier's
   registered key and signature to the same canonical graph hash, the shapes
   version, SHACL report hash, passing outward-scrub result, and provenance
   manifest.

Both keys are existing `aegis:VerifierRegistration` nodes. A Shuttle-derived
bundle additionally binds the seal to the frozen operational-window IRI.
Static packs do not invent a window merely to satisfy the generic envelope.

## 2. Production and verification sequence

The producer MUST execute these steps in order:

1. Close the source graph or Shuttle window to further writes.
2. Run `quipu pack` with explicit shapes and stored queries.
3. Read `pack_manifest.content_hash`; never compute a competing identity.
4. Run `quipu pack --verify` against the emitted file.
5. Run SHACL validation and the outward-share scrub over the bounded content.
6. Emit the publisher attestation and independent certification seal over the
   same hash and manifest inputs.
7. Validate the complete RDF envelope against Quipu's loaded governance
   shapes.
8. Store the file under a content-addressed Garage key and record an
   external-truth mapping (`source_uri`, `access_via`, `freshness`,
   `verified_by`) on the bundle entity.

A consumer given only the bundle IRI resolves the mapping, fetches the bytes,
recomputes the manifest hash, verifies both registered signatures, verifies
the SHACL and scrub evidence, and only then attaches or imports. Import remains
Quipu's quarantined staging flow; certification never grants implicit
promotion.

Garage is the durable cold copy, not the trust root. A successful upload proves
only storage acceptance. The manifest hash proves content identity; the two
registered signatures prove publisher and certifier claims. Retention, bucket
policy, and credential custody are deployment inputs and MUST be audited before
the first production upload.

The implemented producer boundary is:

```bash
scripts/certify_pack.py <graph-iri> --db <source.db> --out <name.qpack.db> \
  --name <name> --version <version> --shape <shape-set> --query <query-name> \
  --shacl-report <conforming-report.json> --publish-dir <durable-root> \
  # plus two distinct public-key/key-IRI/signature inputs and mapping fields
```

It executes Quipu through argument arrays (never a shell), runs `pack --verify`,
and reads `pack_manifest.content_hash` read-only. A Shuttle-derived invocation
without `--frozen-window-iri` refuses. Signatures use Quipu's Ed25519 hex
convention and cover domain-separated canonical claim messages. The producer
refuses a bad signature, reused key identity, non-conforming report, mismatched
report hash, or artifact scrub finding; callers do not supply the scrub boolean
or SHACL hash. Publication is atomic at
`<durable-root>/sha256/<manifest-digest>.qpack.db`; `source_uri` must identify
that exact content-addressed copy.

## 3. Relationship to the Quipu v1 share interface

The `aegis-33cgl` v1 share directory and a Camayoc `.qpack.db` are two physical
projections of one governed semantic object, not competing knowledge formats:

- `.qpack.db` is the single-file, directly attachable Camayoc distribution
  artifact. Its `pack_manifest.content_hash` is the bundle's
  `canonicalGraphHash`.
- `{manifest.json, export.nt, shapes.ttl}` is Quipu's git-native projection for
  review, lineage, diff, and `/import`. Its `share_id` identifies that transport
  envelope and parent chain; it never replaces the canonical graph identity.
- Camayoc invokes Quipu to create either projection. It does not reimplement
  canonical RDF serialization, share-manifest hashing, resolution, or
  quarantine.
- `manifest.producer.name = "quipu"` identifies the canonicalizer. The
  publisher key identifies authorship, and the independent certifier key
  identifies conformance; those three roles must not be collapsed.

Consumers preserve every v1 manifest field and follow Quipu's import contract:
hash/version/path mismatch refuses before parsing; exact entity matches may be
rewritten locally; fuzzy matches remain review candidates; non-conforming or
off-vocabulary facts remain quarantined; certification never promotes directly
to ROOT. The certified bundle's external-truth mapping is the discovery path to
the digest-addressed artifact, while the v1 share directory is the composition
path. Both name the same bounded source and named shapes version.

Garage/S3, git, and OCI are storage or transport adapters over the digest key.
They are not trust roots, do not mint new bundle identities, and do not change
the signed claims. The current producer implements an atomic filesystem adapter;
an S3 adapter must preserve the exact `sha256/<digest>.qpack.db` key contract and
verify the uploaded object before recording its URI.

## 4. Declarative ingress: the Camayoc RML subset

Camayoc also owns the executor for declarative source-to-graph mappings because
this is knowledge ingress, not storage. Mappings are RDF data governed in
Quipu and may travel inside the certified pack above. The normative executor
contract is [rml-executor.md](rml-executor.md); this section only fixes its
relationship to pack production.

The first implementation is a principled materializing subset:

- logical sources: JSON, CSV, and SQLite;
- iterators: JSON paths, CSV rows, and one parameterized SQLite query;
- term maps: constant, reference, and template;
- subject maps and predicate-object maps;
- explicit target type, target graph, source kind, and mapping IRI;
- output through Camayoc's governed Quipu write lane with the mapping IRI as
  provenance;
- deterministic ordering and stable entity names, so executing the same
  mapping twice is byte-identical and idempotent.

The vocabulary stays aligned with RML/R2RML so a mapping remains portable.
Camayoc does not claim spec completeness. Version 1 excludes joins across
logical sources, custom functions, XML, streaming sources, and virtual
query-time federation. Unsupported terms refuse before reading or writing a
source; they never degrade to a best-effort interpretation.

The external-truth quartet delivered by `aegis-jsyl2` is a source-discovery
contract, not executable transformation logic. An executable mapping adds
standard RML/R2RML triples-map data and refers to a governed external-truth
subject. Quipu's loaded vocabulary does not yet include those standard mapping
classes, so loading the Camayoc RML subset shapes is a prerequisite, not work
the executor may silently route around.

The first conformance fixture is a bounded bead-store slice. One declared
mapping must materialize it twice with the same entity names and episode body,
produce one logical result, and name the mapping IRI in provenance. Subsequent
fixtures cover `services.json` and Prometheus scrape targets.

## 5. Interfaces and ownership

| Concern | Owner | Interface |
|---|---|---|
| Pack bytes, manifest hash, attach/import | Quipu | `.qpack.db`, `pack_manifest`, pack CLI |
| Meaning, mapping vocabulary, ingress policy | Camayoc | RDF mappings + governed shapes |
| Publisher signature | Producing principal | `PublisherAttestation` |
| Knowledge certification | Independent certifier | `KnowledgeCertificationSeal` |
| Operational source windows | Shuttle | Frozen-window IRI |
| Durable byte storage | Garage | Content-addressed object key |

There is no second pack class, manifest hash, archive extension, or signature
shortcut. In particular, a Shuttle `TransitionEvent` signature cannot stand in
for either the publisher or certifier claim: it authenticates a transition,
not the finished bounded artifact.

## 6. Acceptance gates

- A static pack and a Shuttle-window pack both conform to the loaded Quipu
  certification shapes; removing either signature or setting scrub pass false
  is refused.
- One source graph produces one `.qpack.db`; its manifest hash is unchanged by
  relocation through git, OCI, and Garage.
- An independent consumer fetches from only the graph mapping, verifies hash
  and both claims, then imports into quarantine.
- The bead-store mapping executes twice byte-identically and yields one logical
  result with provenance naming the mapping IRI.
- Unsupported RML features fail before any Quipu write.
