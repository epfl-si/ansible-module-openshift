#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Create ImageStreams (and their BuildConfigs) with less boilerplate."""

import re
from base64 import b64encode

from ansible.errors import AnsibleActionFail
from ansible.module_utils.six import string_types
from ansible.plugins.action import ActionBase

# There is a name clash with a module in Ansible named "copy":
deepcopy = __import__('copy').deepcopy


DOCUMENTATION = """
---
module: openshift_imagestream
description:
  - Create an ImageStream and (optionally) an associated BuildConfig object
"""

EXAMPLES = """
- name: Just an ImageStream (leaving unspecified how images get into the stream)
  openshift_imagestream:
    metadata:
      name: sometthing-sometting
      namespace: mynamespace
      i-like-to: move-it-move-it

- name: An ImageStream that is simply downloaded from a public registry
  openshift_imagestream:
    metadata:
      name: origin-jenkins-base
      namespace: mynamespace
    tag: latest
    from: docker.quay.io/openshift/origin-jenkins-agent-base

- name: An ImageStream from Docker Hub
  openshift_imagestream:
    metadata:
      name: perl
      namespace: mynamespace
    # In that case you need a structure for `from`, otherwise the action module
    # will guess wrong (i.e. it will assume that we pull from a local image named
    # `perl`):
    from:
      kind: DockerImage
      name: perl:buster

- name: An ImageStream built from an inline Dockerfile
  openshift_imagestream:
    metadata:
      name: foo
      namespace: mynamespace
    from:
      kind: ImageStreamTag
      imageStream: perl
      imageStreamTag: latest
      # Trigger will be added automatically on ImageChange of the above
    dockerfile: |
      FROM perl
      RUN cpan URI::escape
    # Because there is a dockerfile, this one will have a BuildConfig as well

- name: An ImageStream built from a directory living in a Git depot
  openshift_imagestream:
    metadata:
      name: foo
      namespace: mynamespace
    git:
      repository: 'https://github.com/epfl-si/wp-ops'
      ref: wwp-continuous-integration
      path: docker/jenkins
      webhook_secret: 123abc456    # Will be set as part of the URL GitHub-side,
                                   # *not* what GitHub calls a secret
      webhook_secret_name: I-can-choose-a-secret-name-here-otherwise-a-default-one-will-be-used
"""


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        self.result = super(ActionModule, self).run(tmp, task_vars)

        class Run:
            pass

        args = self._task.args

        self.run = Run()
        self.run.name = args.get('name', args.get('metadata', {}).get('name'))
        if not self.run.name:
            raise AnsibleActionFail(
                "Missing field `name` in `openshift_imagestream`")
        self.run.namespace = args.get('namespace', args.get('metadata', {}).get('namespace'))
        if not self.run.name:
            raise AnsibleActionFail(
                "Missing field `namespace` in `openshift_imagestream`")
        self.run.tmp = tmp
        self.run.task_vars = task_vars
        self.run.state = args.get('state', 'latest')
        self.run.metadata = args.get('metadata', {})
        self.run.tag = args.get('tag', 'latest')
        self.run.webhook_secret_name = args.get('git', {}).get('webhook_secret_name', None)
        self.run.webhook_secret = args.get('git', {}).get('webhook_secret', None)
        if self.run.webhook_secret and not self.run.webhook_secret_name:
            self.run.webhook_secret_name = '%s-webhook' % self.run.name

        frm = self._get_from_struct(args.get('from'))
        if self._has_build_steps(args):
            self._run_openshift_imagestream_action()
            self._run_openshift_buildconfig_action(frm, args)
        else:
            self._run_openshift_imagestream_action(frm)

        if self.run.webhook_secret:
            self._run_openshift_secret_action()

        return self.result

    def _run_openshift_action(self, kind, spec=None, data=None, name=None):
        # https://www.ansible.com/blog/how-to-extend-ansible-through-plugins
        # says to look into Ansible's lib/ansible/plugins/action/template.py,
        # which I did.
        if self.result.get('failed'):
            return

        metadata = deepcopy(self.run.metadata or {})
        metadata['name'] = name if name else self.run.name
        metadata['namespace'] = self.run.namespace

        if kind.lower() == "imagestream":
            api_version = "image.openshift.io/v1"
        elif kind.lower() == "buildconfig":
            api_version = "build.openshift.io/v1"
        else:
            api_version = "v1"  # and hope for the best

        args = {
            'state': self.run.state,
            'kind': kind,
            'apiVersion': api_version,
            'metadata': metadata
        }
        if data:  # For secrets
            args['data'] = data
        if spec:  # For everything else
            args['spec'] = spec

        return self._run_action('openshift', args)

    def _run_action(self, action_name, args):
        new_task = self._task.copy()
        new_task.args = args

        subaction = self._shared_loader_obj.action_loader.get(
            action_name,
            task=new_task,
            connection=self._connection,
            play_context=self._play_context,
            loader=self._loader,
            templar=self._templar,
            shared_loader_obj=self._shared_loader_obj)
        self.result.update(subaction.run(task_vars=self.run.task_vars))

    def _run_openshift_imagestream_action(self, frm=None):
        """Create/update/delete the ImageStream Kubernetes object."""
        spec = None
        if frm:
            if frm['kind'] == 'DockerImage':
                spec = {'tags': [{
                    'name': self.run.tag,
                    'from': frm,
                    'importPolicy': {'scheduled': True}
                }]}
            else:
                # Note: tag tracking as described in
                # https://docs.openshift.com/container-platform/3.11/architecture/core_concepts/builds_and_image_streams.html#image-stream-tag
                # is not implemented yet.
                pass

        self._run_openshift_action('ImageStream', spec=spec)

    def _run_openshift_buildconfig_action(self, frm, args):
        """Create/update/delete the BuildConfig Kubernetes object.

        If the `openshift_imagestream` action doesn't just consist of
        a trivial `docker pull` (e.g. it has `dockerfile` or `git`
        arguments), then create a BuildConfig to carry out the build
        step.

        The created BuildConfig always has "output:" -> "to:" set to
        the ImageStream and tag created by the same
        `openshift_imagestream` action, and avoids caching wherever
        possible.
        """
        source = self._get_source_stanza(args)

        spec = {
            'source': source,
            'output': {'to': {'kind': 'ImageStreamTag',
                              'name': '%s:%s' % (self.run.name, self.run.tag)}},
            'strategy': {
                'type': 'Docker',
                'dockerStrategy': {'noCache': True, 'forcePull': True}
            },
            'triggers': self._get_build_triggers(frm, args)
        }

        if 'strategy' in args:
            deepmerge(args['strategy'], spec['strategy'])

        # https://docs.openshift.com/container-platform/3.11/dev_guide/builds/index.html#defining-a-buildconfig
        spec['strategy']['dockerStrategy']['from'] = frm

        self._run_openshift_action('BuildConfig', spec=spec)

    def _run_openshift_secret_action(self):
        """Create/update/delete the Secret Kubernetes object."""

        data = dict(WebHookSecretKey=b64encode(
            self.run.webhook_secret.encode("UTF-8")))
        self._run_openshift_action('Secret', data=data,
                                   name=self.run.webhook_secret_name)

    def _get_source_stanza(self, args):
        if 'source' in args:
            return args['source']
        elif 'dockerfile' in args:
            return {'type': 'Dockerfile', 'dockerfile': args['dockerfile']}
        elif self._get_git_repository(args):
            git = args['git']
            try:
                retval = {
                    'type': 'Git',
                    'git': {'uri': self._get_git_repository(args)}
                }
                if 'ref' in git:
                    retval['git']['ref'] = git['ref']
                if 'path' in git:
                    retval['contextDir'] = git['path']
                return retval
            except KeyError as e:
                raise AnsibleActionFail("Missing field `%s` under `git`" % e.args[0])

    def _get_git_repository (self, args):
        if 'git' not in args:
            return None
        return args['git'].get('repository', None)

    def _has_build_steps(self, args):
        return self._get_source_stanza(args) is not None

    def _get_from_struct(self, from_arg):
        """Returns the "from" sub-structure to use for ImageStreams and BuildConfigs.

        Both are mutually exclusive in practice. A "from"
        sub-structure in an ImageStream means that that image is
        downloaded or copied, not built.
        """
        if not from_arg:
            return None

        if not isinstance(from_arg, string_types):
            return from_arg

        if "/" in from_arg:
            return {
                'kind': 'DockerImage',
                'name': from_arg
            }
        else:
            # Assume the image is a "local" ImageStream (in
            # same namespace). Note: that won't work if what
            # you wanted was to e.g. pull "busybox" from the
            # Docker Hub. Either pass a full Docker URL (e.g.
            # docker.io/busybox), or pas a data structure in
            # the 'from:' argument.
            from_parts = from_arg.split(':', 2)
            if len(from_parts) < 2:
                from_parts.append('latest')
            return {
                'kind': 'ImageStreamTag',
                'name': '%s:%s' % tuple(from_parts),
                'namespace': self.run.namespace
            }

    def _get_build_triggers(self, frm, args):
        triggers = args.get('triggers', [])

        if frm and 'kind' in frm and frm['kind'] == 'ImageStreamTag':
            # Explicit "from" struct in task, with internal
            # ImageStream; trigger on it.
            triggers.append({
                'type': 'ImageChange',
                'imageChange': { 'from': frm }
            })
        elif 'dockerfile' in args:
            def from_line(line):
                return re.match(r'FROM\s+(\S*)', line)

            for from_uri in (from_line(l).group(1) for l in args['dockerfile'].split('\n')
                             if from_line(l)):
                is_local_image = re.match(
                    r'docker-registry.default.svc(?:[:]\d+)?/([^/]*)/(.*)$',
                    from_uri)
                if is_local_image:
                    imagestream_namespace = is_local_image.group(1)
                    imagestream_name_and_tag = is_local_image.group(2)
                    triggers.append({
                        'type': 'ImageChange',
                        'imageChange': {
                            'from': {
                                'kind': 'ImageStreamTag',
                                'namespace': imagestream_namespace,
                                'name': imagestream_name_and_tag
                            }
                        }
                    })

        # Build from webhook if so configured
        # https://docs.openshift.com/container-platform/3.11/dev_guide/builds/triggering_builds.html
        git_repo = self._get_git_repository(args)
        if self.run.webhook_secret:
            if 'github' in git_repo:
                type = 'GitHub'
            elif 'gitlab' in git_repo:
                type = 'GitLab'
            elif 'bitbucket' in git_repo:
                type = 'Bitbucket'
            else:
                type = 'Generic'
            triggers.append({
                'type': type,
                type.lower(): dict(secretReference=dict(
                    name=self.run.webhook_secret_name))
            })

        return triggers

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

