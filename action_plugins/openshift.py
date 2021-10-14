#!/usr/bin/python
# -*- coding: utf-8 -*-

# Imported from the Kubespray project and modified by École
# Polytechnique Fédérale de Lausanne; see ../LICENSE

from io import StringIO
import yaml

from ansible.module_utils.six import string_types
from ansible.plugins.action import ActionBase
from ansible.parsing.yaml.objects import AnsibleUnicode
from ansible.utils.unsafe_proxy import AnsibleUnsafeText
try:
    from ansible.errors import AnsibleError
except ImportError:
    AnsibleError = Exception
try:
    from ansible.template.native_helpers import NativeJinjaText
except ImportError:
    class NativeJinjaText:
        pass

# There is a name clash with a module in Ansible named "copy":
deepcopy = __import__('copy').deepcopy


DOCUMENTATION = """
---
module: _openshift
short_description: Manage state in an OpenShift or Kubernetes Cluster
description:
  - Create, replace, remove, and stop Kubernetes objects
version_added: "2.0"
options:
  name:
    required: false
    default: null
    description:
      - The name associated with the resource
  filename:
    required: false
    default: null
    description:
      - The path and filename of the resource(s) definition file(s).
      - To operate on several files this can accept a comma separated list of files or a list of files.
    aliases: [ 'files', 'file', 'filenames' ]
  content:
    required: false
    default: null
    description:
      - The plain-text YAML to pass to "oc create"'s standard input
  oc:
    required: false
    default: null
    description:
      - The path to the oc (or kubectl) command
      - By default, look for an oc command in the PATH
  namespace:
    required: false
    default: null
    description:
      - The namespace associated with the resource(s)
  kind:
    required: false
    default: null
    description:
      - The resource to perform an action on. pods (po), replicationControllers (rc), services (svc)
  label:
    required: false
    default: null
    description:
      - The labels used to filter specific resources.
  server:
    required: false
    default: null
    description:
      - The url for the API server that commands are executed against.
  force:
    required: false
    default: false
    description:
      - A flag to indicate to force delete, replace, or stop.
  all:
    required: false
    default: false
    description:
      - A flag to indicate delete all, stop all, or all namespaces when checking exists.
  log_level:
    required: false
    default: 0
    description:
      - Indicates the level of verbosity of logging by oc.
  as_user:
    required: false
    default: null
    descriprtion:
      - A string to indicate user impersonation for specific actions on the kubernetes cluster
  state:
    required: false
    choices: ['present', 'absent', 'latest', 'reloaded', 'stopped']
    default: present
    description: |
      present handles checking existence or creating if definition file provided,
      absent handles deleting resource(s) based on other options,
      latest handles creating or updating based on field-by-field diff,
      reloaded handles updating resource(s) definition using definition file,
      stopped handles stopping resource(s) based on other options.
requirements:
  - oc
author: "Kenny Jones (@kenjones-cisco)"
"""

EXAMPLES = """
---

- name: An OpenShift object that Ansible will create or update
  openshift:
    state: latest
    apiVersion: route.openshift.io/v1
    kind: Route
    metadata:
      name: foo
      namespace: my-namespace
    spec:
      host: prometheus-wwp.epfl.ch

---

- name: An OpenShift object with the YAML content as quoted payload
  openshift:
    state: latest
    content: |
      apiVersion: apps/v1
      kind: StatefulSet
      metadata:
        name: prometheus
        namespace: "{{ openshift_namespace }}"
        annotations:
          # Brain-damaged Ansible would parse string values that
          # happen to be valid JSON (!). Hiding them inside the YAML
          # prevents this.
          image.openshift.io/triggers: '[{"from":{"kind":"ImageStreamTag","name":"{{ monitoring_prober_image_name }}:latest"},"fieldPath":"spec.template.spec.containers[?(@.name==\"prober\")].image"}]'
      spec:

"""


def deepmerge(source, destination):
    """Found at https://stackoverflow.com/a/20666342/435004"""
    for key, value in source.items():
        if isinstance(value, dict):
            # get node or create one
            node = destination.setdefault(key, {})
            deepmerge(value, node)
        else:
            destination[key] = value

    return destination


class ActionModule(ActionBase):
    # These arguments are for passing to the _openshift remote task;
    # they make no sense to Kubernetes.
    REMOTE_ARGS = set(['state', 'oc', 'label', 'server',
                       'force', 'all', 'log_level', 'name', 'namespace', 'as_user'])

    def run(self, tmp=None, task_vars=None):
        self.__result = super(ActionModule, self).run(tmp, task_vars)

        self.__task_vars = deepcopy(task_vars)
        self.__tmp = tmp

        remote_args = {}
        for k, v in self._task.args.items():
            if k in self.REMOTE_ARGS or k == 'kind':
                remote_args[k] = v

        args = self._task.args
        if 'content' in args:
            assert isinstance(args['content'], string_types)
            remote_args['content'] = args['content']
            # Former versions of this module resolved the other way
            # round in case the metadata differed from the YAML
            # 'content' field. Since such malformed `openshift` tasks
            # would have always stayed yellow anyway, keeping this
            # behavior for backward compatibility is a non-goal.
            deepmerge(self._parse_object_identity(args['content']), remote_args)
        else:
            content = deepcopy(args)
            for remote_arg in self.REMOTE_ARGS:
                if remote_arg in content:
                    del content[remote_arg]
            # Use YAML (not JSON) as the over-the-wire transport
            # media, so as to preserve null values ("~")
            remote_args['content'] = self._sane_yaml_serialize(content)

            metadata = args.get('metadata', None)
            for field in ('name', 'namespace'):
                if field in metadata:
                    remote_args[field] = metadata[field]

        self._run_task("_openshift", remote_args)

        return self.__result

    def _parse_object_identity(self, content_yaml):
        """Fish `kind`, `name` and (optionally) `namespace` out of a YAML "content" field."""

        parsed = yaml.safe_load(content_yaml)
        retval = {}
        if 'kind' in parsed:
            retval['kind'] = parsed['kind']
        if 'metadata' in parsed:
            metadata = parsed['metadata']
            for trait in ('name', 'namespace'):
                if trait in metadata:
                    retval[trait] = metadata[trait]

        return retval

    def _run_task(self, module_name, module_args):
        # https://www.ansible.com/blog/how-to-extend-ansible-through-plugins
        new_result = self._execute_module(
            module_name=module_name,
            module_args=deepcopy(module_args),
            task_vars=self.__task_vars,
            tmp=self.__tmp)

        result_flags = {}
        for bool_key in ('failed', 'changed'):
            if bool_key in new_result and bool_key in self.__result:
                result_flags[bool_key] = (self.__result[bool_key] or
                                          new_result[bool_key])
        deepmerge(new_result, self.__result)
        deepmerge(result_flags, self.__result)

    def _sane_yaml_serialize(self, struct):
        """Don't get me started on Python string types.

        The Ansible bugware to patch over same is nothing to be proud
        of either...
        """
        stringio = StringIO()
        dumper = yaml.Dumper(stringio)

        def represent_string(dumper, data):
            """Represent a string as a string. Crazy, I know."""
            return dumper.represent_data(str(data))

        dumper.add_representer(AnsibleUnicode, represent_string)
        dumper.add_representer(AnsibleUnsafeText, represent_string)
        dumper.add_representer(NativeJinjaText, represent_string)
        try:
            dumper.open()
            dumper.represent(struct)
            dumper.close()
        finally:
            dumper.dispose()
        return stringio.getvalue()
