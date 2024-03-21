# 1.x release cycle

## 1.10.0

- Introduce `parse_external_docker_tag` filter (lifted from wp-ops)

## 1.9.2 (Aug 25th, 2023)

- Fix typo

## 1.9.1 (July 5th, 2023)

- Fix boneheaded `NameError`

## 1.9.0 (June 28th, 2023)

- Refactor for future maintainability, might have introduced bugs, although I don't think so
- Support immediate, multi-stage Dockerfiles

## 1.8.0 (June 12th, 2023)

- Bugfix: Ansible introduced yet another string wrapper class in its Jinja fixture, which needs a special case passthrough for YAML serialization

## 1.7.3 (Feb 9th, 2023)

- Bugfix: `_openshift.py` file header was defective

## 1.7.3 (Feb 3th, 2023)

- Bugfix: when setting both `from: ~` and `strategy:` → `dockerStrategy:` (which might happen e.g. because of a `with_items` loop), don't pollute the latter with the former — In other words, ignore `from:` when not set.

## 1.7.2 (same day)

Same except the fix didn't actually work, because of a silly operator precedence issue ☹

## 1.7.1 (Nov 4th, 2021)

- Accept `branch:` or `tag:` as aliases for `ref:` under `git:` dict

## 1.7.0 (Nov 4th, 2021)

- Remove default `dockerStrategy:` → `noCache: true` — Meaning that (newly-created) BuildConfig objects will start using the Docker layer cache, as they should

## 1.6.0 (Nov 4th, 2021)

- `state:` now defaults to `latest` (rather than `present`) in `openshift:` and `openshift_imagestream:` tasks

## 1.5.0 (Oct 26th, 2021)

- Fix nevergreen on pod images that get rewritten under the influence of OpenShift triggers

## 1.4.0 (Oct 20th, 2021)

- Support user-specified `openshift_imagestream:` → `spec:` (required for e.g. build resource limits)

## 1.3.0 (Oct 20th, 2021)

- Do the right thing for `openshift_imagestream:` stanzas that are mirrors (i.e. with a `from:` line and nothing else)

## 1.2.0 (Sep 23rd, 2021)

- Fix `source:`-less `openshift_imagestream`s. These were supposed to mirror e.g. Docker Hub, but that wasn't happening as experimentation suggests that `"referencePolicy": { "type": "Source" }` inhibits `"importPolicy": { "scheduled": True }`. Forcibly set `"referencePolicy": { "type": "Local" }` for such `openshift_imagestream`s.

## 1.1.0 (Aug 27th, 2021)

- Top-level `dockerfile:` (just below `openshift_imagestream:`) is now deprecated; we now prefer a `source:` → `dockerfile:` structure that mimics the BuildConfig type definition. (The older form is still supported, as is the automagic addition of `type: Dockerfile` if omitted)

## 1.0.1 (Aug 26th, 2021)

- Support “`from:`-less” `openshift_imagestream`s (with a `dockerfile:` but no `from:`), also when the FROM line in the Dockerfile references a local OpenShift image e.g. `FROM docker-registry.default.svc:5000/namespace/name:tag`; in that case, synthesize a proper `from:` block (it being the only way that such a BuildConfig can possibly succeed, owing to considerations of authentication to the OpenShift registry)

## 1.0.0 (Aug 26th, 2021)

First numbered release

- Don't insist on `docker pull`ing `FROM` images all the time anymore; we now live in a Docker-Hub-ratelimited world
