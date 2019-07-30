#!/usr/bin/python # -*- coding: utf-8 -*-

"""Back-end (remote) half of the "openshift" action plugin."""

# Imported from the Kubespray project and modified by École
# Polytechnique Fédérale de Lausanne; see ../LICENSE

import json
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

    def run(self):
        state = self.module.params.get('state')
        if state == 'present':
            return self.create()

        elif state == 'absent':
            return self.delete()

        elif state == 'reloaded':
            return self.replace()

        elif state == 'stopped':
            return self.stop()

        elif state == 'latest':
            return self.replace()

        else:
            raise AnsibleError('Unrecognized state %s.' % state)

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
        return self.module.exit_json(changed=True, rc=rc, stdout=out)

    def _execute_nofail(self, cmd):
        args = self.base_cmd + cmd
        rc, out, err = self.module.run_command(args)
        return rc == 0

    def create(self, check=True, force=True):
        if check and self.exists():
            return self.module.exit_json(changed=False)

        cmd = ['apply']

        if force:
            cmd.append('--force')
        if self.as_admin:
            cmd.append('--as=system:admin')

        if self.content is not None:
            cmd.extend(['-f', '-'])
            return self._execute(cmd, data=self.content)
        elif self.filename:
            cmd.append('--filename=' + ','.join(self.filename))
            return self._execute(cmd)
        else:
            raise AnsibleError('filename or content required')

    def replace(self, force=True):
        rc, out, err = self.module.run_command(
            self.base_cmd
            + ['get', '--no-headers', '-o', 'json']
            + self._get_oc_flags())
        if not rc:
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

            if self._is_same_configuration(new_state, current_state):
                return self.module.exit_json(changed=False)

        cmd = ['apply']

        if force:
            cmd.append('--force')
        if self.as_user is not None:
            cmd.append('--as='+ self.as_user)

        if self.content is not None:
            cmd.extend(['-f', '-'])
            return self._execute(cmd, data=self.content)
        elif self.filename:
            cmd.append('--filename=' + ','.join(self.filename))
            return self._execute(cmd)
        else:
            raise AnsibleError('filename required to reload')

    def delete(self):

        if not self.force and not self.exists():
            return self.module.exit_json(changed=False)

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

        return self._execute(cmd)

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
            return self.module.exit_json(changed=False)

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

    def _is_same_configuration(self, c_ansible, c_live):
        """True iff c_live is a faithful Kubernetes-side image of c_ansible.

        Args:
          c_live: A value or subtree of the YAML configuration
                  stored in Ansible
          c_ansible: The corresponding value or subtree in the same tree
                  position inside the live object.

        Used in "state: latest" mode; if this function returns true,
        the update is skipped (i.e. the Ansible status will be a no-op
        green).

        Scalar values are compared for strict identity. List values
        must match in length and each entry must match pairwise
        (recursing through the _is_same_configuration method again).
        Dict values must be a subset on c_ansible side (again,
        recursing through _is_same_configuration for each key in
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
            return True
        if c_ansible == [] or c_ansible == {}:
            # User has explicitly set an empty data structure in their
            # Ansible-side config. Interpret that as wanting the same
            # data structure to be empty on the live side as well.
            return not c_live

        if is_list(c_ansible) and is_list(c_live):
            if len(c_ansible) != len(c_live):
                return False
            for (c_a, c_l) in zip(c_ansible, c_live):
                if not self._is_same_configuration(c_a, c_l):
                    return False
            return True
        elif is_dict(c_ansible) and is_dict(c_live):
            for k in c_ansible.keys():
                if not self._is_same_configuration(
                        c_ansible[k],
                        # Still recurse if the key does not exist in live.
                        # self._is_same_configuration(c_ansible=...,
                        # c_live=None) can indeed return True in case
                        # c_ansible is an empty structure; see
                        # previous comment.
                        c_live.get(k, None)):
                    return False
            # Ignore any c_live keys that are missing in c_ansible;
            # assume Kubernetes put them there automagically (e.g.
            # "status"). If that is not the case and the operator
            # wants to suppress the key, they can do so by passing an
            # empty list or dict or a null value ("~" in YAML) for at
            # least one Ansible run.
            return True
        else:
            return False


if __name__ == '__main__':
    OpenshiftRemoteTask().run()
