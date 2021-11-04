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
            state=dict(default='latest', choices=['present', 'absent', 'latest', 'reloaded', 'stopped']),
            as_user=dict( type='str'),
        ),
        mutually_exclusive=[['filename', 'content']])

    def __init__(self):
        self.module = AnsibleModule(supports_check_mode=True, **self.module_spec)
        self.supports_check_mode = True  # See _apply(), below

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

        self.result = {}

    def run(self):
        state = self.module.params.get('state')
        if state == 'present':
            self.create()
        elif state == 'absent':
            self.delete()
        elif state == 'reloaded':
            self.replace()
        elif state == 'latest':
            self.replace()
        else:
            raise AnsibleError('Unrecognized state %s.' % state)

        self.module.exit_json(**self.result)

    def create(self):
        if self.exists():
            return

        self.result.update(self._apply())

    def _apply(self):
        if self.module.check_mode:
            # Pretend we tried, and it worked
            return dict(changed=True)

        args = ['apply']
        if self.force:
            args.append('--force')
        if self.as_user is not None:
            args.append('--as='+ self.as_user)
        result = self._run_oc_and_pass_the_yaml(args)
        result['changed'] = True
        return result

    def replace(self):
        result = self._run_oc(['get', '--no-headers', '-o', 'json']
                              + self._get_search_flags())
        if not result['rc']:
            # Object already exists; figure out whether we need to patch it
            current_state = json.loads(result['stdout'])

            # Have the API server normalize the data, expand default values
            # etc. for us, so that we get a clean diff
            result = self._run_oc_and_pass_the_yaml(['create', '--dry-run', '-o', 'json'])
            if result['rc']:
                raise AnsibleError("Unable to apply --dry-run the provided configuration\nstdout:\n" + result['stdout'] + "\nstderr:\n" + result['stderr'])
            new_state = json.loads(result['stdout'])

            raw_diffs = [d for d in self._find_diff_points(new_state, current_state)
                         if not self._is_diff_irrelevant(d, current_state)]
            diffs = [
                dict(before_header=".".join(map(str, diff_point[0])),
                     after_header=".".join(map(str, diff_point[0])),
                     before=str(diff_point[1]),
                     after=str(diff_point[2]))
                for diff_point in raw_diffs]
            if not diffs:
                return   # Nothing to do

            # As per https://github.com/kubernetes/kubernetes/issues/70674,
            # updates that don't specify a metadata.resourceVersion undergo some
            # kind of hazard of being rejected (depending on whether they have ever been
            # edited with something like `kubectl apply` or `oc apply`, IIUC).
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
            diffs = [dict(
                before_header="(non-existent)",
                before="", after=self.content
            )]

        # Now do it
        writeresult = self._apply()
        self.result.update(writeresult)
        if writeresult.get('rc', 0) == 0:
            # Success (or check mode) - Keep the diff for -v
            self.result['diff'] = diffs

    def delete(self):
        if not self.force and not self.exists():
            return

        result = self._run_oc(['delete'] + self._get_search_flags())
        if result['rc'] == 0:
            self.result.update({'changed': True})
        else:
            self.result.update(result)

    def _get_search_flags(self):
        """Return: The flags to pass to oc for exists() or delete() purposes."""
        args = []
        if self.filename:
            args.append('--filename=' + ','.join(self.filename))
        else:
            if not self.kind:
                raise AnsibleError('resource required without filename')

            args.append(self.kind)

            if self.name:
                args.append(self.name)

            if self.label:
                args.append('--selector=' + self.label)

            if self.all:
                args.append('--all-namespaces')
            if self.as_user is not None:
                args.append('--as='+ self.as_user)

        return args

    def exists(self):
        return self._run_oc(['get', '--no-headers'] + self._get_search_flags())['rc'] == 0

    def _run_oc(self, args, stdin=None):
        try:
            rc, out, err = self.module.run_command(self.base_cmd + args, data=stdin)
        except Exception as exc:
            raise AnsibleError(
                'error running command (%s): %s' % (' '.join(self.base_cmd + args), str(exc)))
        return dict(rc=rc, stdout=out, stderr=err)

    def _run_oc_and_pass_the_yaml(self, args):
        if self.content is not None:
            return self._run_oc(args + ['-f', '-'], stdin=self.content)
        elif self.filename:
            return self._run_oc(args + '--filename=' + ','.join(self.filename))
        else:
            return AnsibleError('must set either content or filename')

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

    def _is_diff_irrelevant(self, diff, current_state):
        """True iff this diff should be ignored.

        We ignore diffs when the `image` of a container is being set by
        OpenShift itself (e.g. from an ImageStream and a trigger).
        """
        where, before, after = diff

        if len(where) > 3 and where[-3] == 'containers' and where[-1] == 'image':
            if '@sha256:' in before and not '@sha256:' in after:
                # We could be pickier here, and check whether current_state has a
                # matching trigger.
                return True

        return False

if __name__ == '__main__':
    OpenshiftRemoteTask().run()
