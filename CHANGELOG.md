# 1.x release cycle

## 1.0.1 (Aug 26th, 2021)

- Support “`from:`-less” `openshift_imagestream`s (with a `dockerfile:` but no `from:`), also when the FROM line in the Dockerfile references a local OpenShift image e.g. `FROM docker-registry.default.svc:5000/namespace/name:tag`; in that case, synthesize a proper `from:` block (it being the only way that such a BuildConfig can possibly succeed, owing to considerations of authentication to the OpenShift registry)

## 1.0.0 (Aug 26th, 2021)

First numbered release

- Don't insist on `docker pull`ing `FROM` images all the time anymore; we now live in a Docker-Hub-ratelimited world
