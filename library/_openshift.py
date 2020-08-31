#!/usr/bin/python # -*- coding: utf-8 -*-

"""Back-end (remote) half of the "openshift" action plugin."""

# Imported from the Kubespray project and modified by École
# Polytechnique Fédérale de Lausanne; see ../LICENSE

import json
import re
import types
import sys

from ansible.module_utils.basic import AnsibleModule
try:
    from ansible.errors import AnsibleError
except ImportError:
    AnsibleError = Exception


class OpenshiftRemoteTask(object):

    module_spec = dict(
        argument_spec=dict(
            kind=dict(aliases=['resource']),
            name={},
            namespace={},
            filename=dict(type='list', aliases=['files', 'file', 'filenames']),
            content=dict(type='str'),
            label={},
            server={},
            oc={},
            force=dict(default=False, type='bool'),
            all=dict(default=False, type='bool'),
            log_level=dict(default=0, type='int'),
            state=dict(default='present', choices=['present', 'absent', 'latest', 'reloaded', 'stopped']),
            as_user=dict( type='str'),
        ),
        mutually_exclusive=[['filename', 'content']])

    def __init__(self):
        self.module = AnsibleModule(**self.module_spec)

        self.oc = self.module.params.get('oc')
        if self.oc is None:
            self.oc = self.module.get_bin_path('oc', True, ['/opt/bin'])
        self.base_cmd = [self.oc]

        if self.module.params.get('server'):
            self.base_cmd.append('--server=' + self.module.params.get('server'))

        if self.module.params.get('log_level'):
            self.base_cmd.append('--v=' + str(self.module.params.get('log_level')))

        if self.module.params.get('namespace'):
            self.base_cmd.append('--namespace=' + self.module.params.get('namespace'))

        self.all = self.module.params.get('all')
        self.force = self.module.params.get('force')
        self.name = self.module.params.get('name')
        self.filename = [f.strip() for f in self.module.params.get('filename') or []]
        self.content = self.module.params.get('content', None)
        self.kind = self.module.params.get('kind')
        self.label = self.module.params.get('label')
        self.as_user=self.module.params.get('as_user')

        self.result = dict(changed={})

    def run(self):
        state = self.module.params.get('state')
        if state == 'present':
            self.create()
        elif state == 'absent':
            self.delete()
        elif state == 'reloaded':
            self.replace()
        elif state == 'stopped':
            self.stop()
        elif state == 'latest':
            self.replace()
        else:
            raise AnsibleError('Unrecognized state %s.' % state)

        self.module.exit_json(**self.result)

    def _execute(self, cmd, **kwargs):
        args = self.base_cmd + cmd
        try:
            rc, out, err = self.module.run_command(args, **kwargs)
            if rc != 0:
                raise AnsibleError(
                    'error running oc (%s) command (rc=%d), out=\'%s\', err=\'%s\'' % (' '.join(args), rc, out, err))
        except Exception as exc:
            raise AnsibleError(
                'error running oc (%s) command: %s' % (' '.join(args), str(exc)))
        self.result.update(rc=rc, stdout=out)
        return

    def _execute_nofail(self, cmd):
        args = self.base_cmd + cmd
        rc, out, err = self.module.run_command(args)
        return rc == 0

    def create(self, check=True):
        if self.exists():
            return

        cmd = ['apply']

        if self.force:
            cmd.append('--force')
        if self.as_user is not None:
            cmd.append('--as='+ self.as_user)
        if self.content is not None:
            cmd.extend(['-f', '-'])
            self._execute(cmd, data=self.content)
        elif self.filename:
            cmd.append('--filename=' + ','.join(self.filename))
            self._execute(cmd)
        else:
            raise AnsibleError('filename or content required')
        self.result.update({'changed': True})

    def replace(self):
        rc, out, err = self.module.run_command(
            self.base_cmd
            + ['get', '--no-headers', '-o', 'json']
            + self._get_oc_flags())
        if not rc:
            # Object already exists; figure out whether we need to patch it
            current_state = json.loads(out)
            cmd = self.base_cmd + ['create', '--dry-run', '-o', 'json']
            if self.content is not None:
                cmd.extend(['-f', '-'])
                rc, out, err = self.module.run_command(cmd, data=self.content)
            elif self.filename:
                cmd.append('--filename=' + ','.join(self.filename))
                rc, out, err = self.module.run_command(cmd)
            if rc:
                raise AnsibleError('Unable to apply --dry-run the provided configuration\n' + out + err)
            new_state = json.loads(out)

            changed = { 'paths': list(self._find_diff_points(new_state, current_state)) }
            if not changed['paths']:
                return   # Nothing to do

            # As per https://github.com/kubernetes/kubernetes/issues/70674,
            # updates that don't specify a metadata.resourceVersion undergo some
            # kind of hazard of being rejected (depending on whether they have ever been
            # edited with something `kubectl apply` or `oc apply`, IIUC).
            # So add a metadata.resourceVersion if we can find one.
            if 'metadata' in current_state and 'resourceVersion' in current_state['metadata']:
                resource_version = current_state['metadata']['resourceVersion']

                self.content = re.sub(
                    r"""
                      ^ (metadata:\s*\n)              # metadata is expected at top level
                        ( (?:  \s*  [#] .* \n)*  )    # Any number of comment lines
                        ( \s+ ) ( \w )                # Indented block under metadata:
                    """,
                    r'\1\2\3resourceVersion: "%s"\n\3\4' % re.escape(str(resource_version)),
                    self.content,
                    flags=re.MULTILINE|re.VERBOSE)
        else:
            changed = {'created': True}

        cmd = ['apply']
        if self.force:
            cmd.append('--force')
        if self.as_user is not None:
            cmd.append('--as='+ self.as_user)

        if self.content is not None:
            cmd.extend(['-f', '-'])
            self._execute(cmd, data=self.content)
        elif self.filename:
            cmd.append('--filename=' + ','.join(self.filename))
            self._execute(cmd)
        else:
            raise AnsibleError('filename required to reload')

        self.result['changed'].update(changed)

    def delete(self):

        if not self.force and not self.exists():
            return

        cmd = ['delete']

        if self.filename:
            cmd.append('--filename=' + ','.join(self.filename))
        else:
            if not self.kind:
                raise AnsibleError('resource required to delete without filename')

            cmd.append(self.kind)

            if self.name:
                cmd.append(self.name)

            if self.label:
                cmd.append('--selector=' + self.label)

            if self.all:
                cmd.append('--all')

            if self.force:
                cmd.append('--ignore-not-found')
            if self.as_user is not None:
                cmd.append('--as='+ self.as_user)

        self._execute(cmd)
        self.result.update({'changed': True})

    def _get_oc_flags(self):
        cmd = []
        if self.filename:
            cmd.append('--filename=' + ','.join(self.filename))
        else:
            if not self.kind:
                raise AnsibleError('resource required without filename')

            cmd.append(self.kind)

            if self.name:
                cmd.append(self.name)

            if self.label:
                cmd.append('--selector=' + self.label)

            if self.all:
                cmd.append('--all-namespaces')
            if self.as_user is not None:
                cmd.append('--as='+ self.as_user)


        return cmd

    def exists(self):
        return self._execute_nofail(['get', '--no-headers'] + self._get_oc_flags())

    # TODO: This is currently unused, perhaps convert to 'scale' with a replicas param?
    def stop(self):

        if not self.force and not self.exists():
            return 

        cmd = ['stop']

        if self.filename:
            cmd.append('--filename=' + ','.join(self.filename))
        else:
            if not self.kind:
                raise AnsibleError('resource required to stop without filename')

            cmd.append(self.kind)

            if self.name:
                cmd.append(self.name)

            if self.label:
                cmd.append('--selector=' + self.label)

            if self.all:
                cmd.append('--all')

            if self.force:
                cmd.append('--ignore-not-found')
            if self.as_user is not None:
                cmd.append('--as='+ self.as_user)


        return self._execute(cmd)

    def _find_diff_points(self, c_ansible, c_live, path=[]):
        """Enumerate all points where `c_ansible` is *not* a superset of `c_live`.

        Args:
          c_live: A value or subtree of the YAML configuration
                  stored in Ansible
          c_ansible: The corresponding value or subtree in the same tree
                  position inside the live object.

        Scalar values are compared for strict identity. List values
        must match in length and each entry must match pairwise
        (recursing through the _find_diff_points method again).
        Dict values must be a subset on c_ansible side (again,
        recursing through _find_diff_points for each key in
        c_ansible); unlike lists, extraneous keys in c_live are
        ignored, under the assumption that Kubernetes put them there
        (e.g. "state", "metadata").

        As a special case, an empty list or dict in c_ansible
        (anywhere in the structure, thanks to recursion) can only
        match with an empty or missing structure on the c_live side at
        the same position in the tree. This provides the Ansible
        playbook author with a way to ensure that some data structure
        (hopefully one that is *not* autocreated by Kubernetes) is
        set to empty.

        Yields: (path, substruct_ansible, substruct_live) tuples
          indicating points of discrepancy, where `path` is a list of
          ints (when descending through a YAML list) and/or string
          keys (when descending through a YAML dict)
        """
        def is_list(u):
            return isinstance(u, list)

        def is_dict(u):
            return isinstance(u, dict)


        if c_ansible == c_live:
            # Does small work of scalar types, including None; and if
            # complex data structures do happen to have perfect
            # equality, that's fine by us as well (and also very
            # likely faster to check than through recursion).
            return
        elif c_ansible == [] or c_ansible == {}:
            # User has explicitly set an empty data structure in their
            # Ansible-side config. Interpret that as wanting the same
            # data structure to be empty on the live side as well.
            if c_live:
                yield (path, c_live, c_ansible)

        elif is_list(c_ansible) and is_list(c_live):
            if len(c_ansible) != len(c_live):
                # No subsetting allowance for lists; length mismatch means
                # a black mark.
                yield (path, c_live, c_ansible)
            else:
                for (i, (c_a, c_l)) in enumerate(zip(c_ansible, c_live)):
                    descend_path = path + [i]
                    for y in self._find_diff_points(c_a, c_l, descend_path):
                        yield y
        elif is_dict(c_ansible) and is_dict(c_live):
            for k in c_ansible.keys():
                descend_path = path + [k]
                for y in self._find_diff_points(
                    c_ansible[k],
                    # Still go through with the recursion if `k` does
                    # not exist in c_live, because we need to
                    # distinguish whether c_ansible[k] is falsy as
                    # well (see previous comment).
                    c_live.get(k, None),
                    descend_path):
                  yield y
            # Conversely, ignore any c_live keys that are missing in
            # c_ansible; assume Kubernetes put them there
            # automagically (e.g. "status"). If that is not the case
            # and the operator wants to suppress the key, they can do
            # so by passing an empty list or dict or a null value ("~"
            # in YAML) for at least one Ansible run.
        else:
            # Simplest case comes last, e.g. two differing scalars
            yield (path, c_live, c_ansible)


if __name__ == '__main__':
    OpenshiftRemoteTask().run()
