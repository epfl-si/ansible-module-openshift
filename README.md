`epfl_si.ansible_module_openshift`
=========

This role provides the `openshift` module, that you can use to create
an `openshift` task:

```yaml
- name: "My ImageStream"
  openshift:
    state: latest
    kind: ImageStream
    metadata:
      name: "{{ image_name }}"
      namespace: "{{ openshift_namespace }}
      labels:
        app: MyApp
```

This ensures that the Kubernetes object of the provided `name` and
`namespace` exists and (under `state: latest`) that the desired state
(in the Ansible YAML structure) is a strict subset of the in-cluster
state (as retrieved with `oc get -o yaml`). If that is not the case,
the role applies the desired mutations (using `oc apply` if the object
already exists, and `oc create` otherwise).

This role also provides the `openshift_imagestream` modules, which
facilitates the task of declaring OpenShift's `ImageStream` and
`BuildConfig` objects. For instance, here is how to set up mirroring
an image from Docker Hub:

```yaml
- name: "Pull upstream awx image into the Docker registry"
  openshift_imagestream:
    metadata:
      name: awx
      namespace: wwp-test
    from: "docker-registry.default.svc:5000/wwp-test/awx:22.4.0"
    tag: "22.x"
```

Here is how to build an image on top of an existing ImageStream
(creating two Kubernetes objects, one of `kind: BuildConfig` to
describe the build process and another of `kind: ImageStream` to store
the resulting image into):

```yaml
- name: "Patch upstream AWX into wp-awx"
  register: _awx_buildconfig
  openshift_imagestream:
    metadata:
      name: wp-awx
      namespace: wwp-test
    dockerfile: |
       FROM docker-registry.default.svc:5000/wwp-test/awx:22.x
       [...]
    tag: "{{ awx_version }}"
```

All the relevant bells and whistles will be set up automatically,
including dependency chaining i.e. `wp-awx` will auto-rebuild whenever
`awx` is updated in that particular tag `22.x`.

Requirements
------------

- A working `oc` or `kubectl` command
- Suitable access to the cluster (i.e. you must be logged in prior to
  running a task that uses this module)

Example Playbook
----------------


```yaml
    - hosts: all
      roles:
         # Loads library/openshift.py to make it available to other plays;
         # does nothing else by itself
         - { role: epfl_si.openshift_module }
   - hosts: all
     tasks:
     - name: "My ImageStream"
       openshift:
         state: latest
         kind: ImageStream
         metadata:
           name: "{{ image_name }}"
           namespace: "{{ openshift_namespace }}"
           labels:
             app: MyApp
```

[See additional documentation in the source code](library/openshift.py)

License
-------

This work may be freely distributed and re-used under the terms of
[the Apache License v2.0](https://www.apache.org/licenses/LICENSE-2.0)

This work contains code initially authored as part of
[Kubespray](https://github.com/kubernetes-sigs/kubespray/), reproduced
and modified with permission under the terms of that same License.

Author Information
------------------

Please contact EPFL IDEV-FSD <idev-fsd@groupes.epfl.ch>.
