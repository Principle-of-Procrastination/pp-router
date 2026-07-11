# Design

## Public API

Remove `/session`, session signing, frontend login state, and the two application-auth secrets. Rate chat requests first through a process-wide bucket and then through an IP bucket. Keep a separate IP bucket for history reads. The NoSQL collection remains `ADMINONLY`; `/history` returns usage metadata with an empty query field.

## Chinese classifier

Keep the deterministic local overlay on LiteLLM's classifier. Score user text, not system-role instructions, using longest non-overlapping matches for actions, technical domains, constraints, deliverables, evaluation dimensions, composition, and scale patterns. Promote diagnostic reasoning and multi-criteria decisions to `REASONING`; promote constraint-heavy, multi-deliverable, or scaled work to `COMPLEX`.

## Dependency policy

Pin the latest stable LiteLLM release exactly, regenerate `uv.lock` and `requirements.txt`, and validate the imported `Router` and `ComplexityRouter` APIs through existing tests. Do not adopt release candidates.
