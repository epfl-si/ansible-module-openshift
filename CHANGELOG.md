# 1.x release cycle

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
