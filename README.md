`epfl_idevelop.ansible_module_openshift`
=========

This role provides the `openshift` module, that you can use to create
an `openshift` task:

```yaml
- name: "My ImageStream"
  openshift:
    state: latest
    kind: ImageStream
    name: "{{ image_name }}"
    namespace: "{{ openshift_namespace }}"
    content: |
      kind: ImageStream
      apiVersion: v1
      metadata:
        name: "{{ image_name }}"
        namespace: "{{ openshift_namespace }}"
        labels:
          app: MyApp
```

This ensures that the Kubernetes object of the provided `name` and
`namespace` exists and (under `state: latest`) that the desired state
(under `content: |`) is a strict subset of the in-cluster state (as
retrieved with `oc get -o yaml`). If that is not the case, the role
applies the desired mutations (using `oc apply` if the object already
exists, and `oc create` otherwise).

Requirements
------------

- A working `oc` or `kubectl` command
- Suitable access to the cluster (i.e. you must be logged in prior to
  running atask that uses this module)

Example Playbook
----------------


```yaml
    - hosts: all
      roles:
         # Loads library/openshift.py to make it available to other plays;
         # does nothing else by itself
         - { role: epfl-idevelop.openshift_module }
   - hosts: all
     tasks:
     - name: "My ImageStream"
       openshift:
         state: latest
         kind: ImageStream
         name: "{{ image_name }}"
         namespace: "{{ openshift_namespace }}"
         content: |
           kind: ImageStream
           apiVersion: v1
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
