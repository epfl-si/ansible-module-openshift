#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Create ImageStreams (and their BuildConfigs) with less boilerplate."""

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
- name: An ImageStream that is simply downloaded from a public registry
  openshift_imagestream:
    name: origin-jenkins-base
    namespace: mynamespace
    tag: latest
    from: docker.quay.io/openshift/origin-jenkins-agent-base
    metadata:
      i-like-to: move-it-move-it

- name: An ImageStream from Docker Hub
  openshift_imagestream:
    name: perl
    namespace: mynamespace
    from: perl

- name: An ImageStream built from an inline Dockerfile
  openshift_imagestream:
    name: foo
    namespace: mynamespace
    from:
      imageStream: perl
      imageStreamTag: latest
      # Trigger will be added automatically on ImageChange of the above
    dockerfile: |
      FROM perl
      RUN cpan URI::escape
    # Because there is a dockerfile, this one will have a BuildConfig as well

- name: An ImageStream built from a directory living in a Git depot
  openshift_imagestream:
    name: foo
    namespace: mynamespace
    git:
      repository: 'https://github.com/epfl-idevelop/wp-ops'
      ref: wwp-continuous-integration
      path: docker/jenkins
"""


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        self.result = super(ActionModule, self).run(tmp, task_vars)

        class Run:
            pass

        args = self._task.args

        self.run = Run()
        try:
            self.run.name = args['name']
            self.run.namespace = args['namespace']
        except KeyError as e:
            raise AnsibleActionFail(
                "Missing field `%s` in `openshift_imagestream`" % e.args[0])
        self.run.tmp = tmp
        self.run.task_vars = task_vars
        self.run.state = args.get('state', 'latest')
        self.run.metadata = args.get('metadata')
        self.run.tag = args.get('tag', 'latest')

        self._run_openshift_imagestream_action(args)
        self._maybe_run_openshift_buildconfig_action(args)

        return self.result

    def _run_openshift_action(self, kind, spec=None):
        # https://www.ansible.com/blog/how-to-extend-ansible-through-plugins
        # says to look into Ansible's lib/ansible/plugins/action/template.py,
        # which I did.
        if self.result.get('failed'):
            return

        metadata = deepcopy(self.run.metadata)
        metadata['name'] = self.run.name
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
        if spec:
            args['spec'] = spec

        return self._run_action('openshift', args)

    def _run_action(self, action_name, args):
        new_task = self._task.copy()
        new_task.args = args

        openshift_action = self._shared_loader_obj.action_loader.get(
            action_name,
            task=new_task,
            connection=self._connection,
            play_context=self._play_context,
            loader=self._loader,
            templar=self._templar,
            shared_loader_obj=self._shared_loader_obj)
        self.result.update(openshift_action.run())

    def _run_openshift_imagestream_action(self, args):
        frm = self._get_from_struct(args)
        if frm and frm['kind'] == 'DockerImage':
            spec = {'tags': [{
                'name': self.run.tag,
                'from': frm,
                'importPolicy': {'scheduled': True}
            }]}
        else:
            # Note: tag tracking as described in
            # https://docs.openshift.com/container-platform/3.11/architecture/core_concepts/builds_and_image_streams.html#image-stream-tag
            # is not implemented yet.
            spec = None

        self._run_openshift_action('ImageStream', spec)

    def _maybe_run_openshift_buildconfig_action(self, args):
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
        if not source:
            return

        spec = {
            'source': source,
            'output': {'to': {'kind': 'ImageStreamTag',
                              'name': '%s:%s' % (self.run.name, self.run.tag)}},
            'strategy': {
                'type': 'Docker',
                'dockerStrategy': {'noCache': True, 'forcePull': True}
            },
            'triggers': args.get('triggers', [])
        }

        frm = self._get_from_struct(args)
        if frm:
            # https://docs.openshift.com/container-platform/3.11/dev_guide/builds/index.html#defining-a-buildconfig
            spec['strategy']['dockerStrategy']['from'] = frm
            # https://docs.openshift.com/container-platform/3.11/dev_guide/builds/triggering_builds.html#image-change-triggers
            spec['triggers'] += [{'type': 'ImageChange'}]

        self._run_openshift_action('BuildConfig', spec)

    def _get_source_stanza(self, args):
        if 'dockerfile' in args:
            return {'type': 'Dockerfile', 'dockerfile': args['dockerfile']}
        elif 'git' in args:
            git = args['git']
            try:
                retval = {
                    'type': 'Git',
                    'git': {'uri': git['repository']}
                }
                if 'ref' in git:
                    retval['git']['ref'] = git['ref']
                if 'path' in git:
                    retval['contextDir'] = git['path']
                return retval
            except KeyError as e:
                raise AnsibleActionFail("Missing field `%s` under `git`" % e.args[0])

    def _get_from_struct(self, args):
        """Returns the "from" sub-structure for ImageStreams and BuildConfigs."""
        if 'from' not in args:
            return None
        if not args['from']:
            return None

        if not isinstance(args['from'], string_types):
            return args['from']

        if "/" in args['from']:
            return {
                'kind': 'DockerImage',
                'name': args['from']
            }
        else:
            # Assume the image is a "local" ImageStream (in
            # same namespace). Note: that won't work if what
            # you wanted was to e.g. pull "busybox" from the
            # Docker Hub. Either pass a full Docker URL (e.g.
            # docker.io/busybox), or pas a data structure in
            # the 'from:' argument.
            from_parts = args['from'].split(':', 2)
            if len(from_parts) < 2:
                from_parts.append('latest')
            return {
                'kind': 'ImageStreamTag',
                'name': '%s:%s' % tuple(from_parts),
                'namespace': self.run.namespace
            }
