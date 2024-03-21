"""Parse a string of the form `foo.bar/myimage:mytag`

This is a convenient helper to compute various fields in `openshift` and
`openshift_imagestream` that are related to images.

Usage:

    "ubuntu:latest" | parse_external_docker_tag

returns a Python structure that would read like this in YAML:

    shortname: ubuntu
    uri: docker.io/library/ubuntu
    tag: latest
    qualified: docker.io/library/ubuntu:latest

Additionally, if the optional `mirrored_base` parameter is set, e.g.

    "ubuntu:latest" | parse_external_docker_tag(mirrored_base="si-quay.epfl.ch/my-namespace")

then the result will contain an additional key like this,

    # ...
    mirrored: si-quay.epfl.ch/my-namespace/ubuntu:latest

"""

class FilterModule(object):
    def filters(self):
        return {
            'parse_external_docker_tag': self.parse_external_docker_tag
        }

    def parse_external_docker_tag(self, docker_tag, mirrored_base=None):
        if ":" in docker_tag:
            (uri, tag) = docker_tag.split(":", 1)
        else:
            uri = docker_tag
            tag = "latest"

        uri_parts = uri.split("/")
        if len(uri_parts) == 1:
            uri_parts = ["docker.io", "library"] + uri_parts
        elif len(uri_parts) == 2:
            uri_parts = ["docker.io"] + uri_parts
        uri = "/".join(uri_parts)

        shortname = uri_parts[-1]

        ret = dict(shortname=shortname, uri=uri, tag=tag,
                    qualified="%s:%s" % (uri, tag))
        if mirrored_base is not None:
            ret["mirrored"]="%s/%s:%s" % (mirrored_base, shortname, tag)

        return ret
