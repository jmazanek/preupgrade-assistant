# -*- coding: utf-8 -*-

"""
Class creates a set of packages for migration scenario
"""

from __future__ import print_function, unicode_literals
import os
import six

from preup.utils import get_file_content


class YumGroupManager(object):
    """more intelligent dict; enables searching in yum groups"""
    def __init__(self):
        self.groups = {}

    def add(self, group):
        self.groups[group.name] = group

    def find_match(self, packages):
        """is there a group whose packages are subset of argument 'packages'?"""
        groups = []
        for group in six.itervalues(self.groups):
            if len(group.required) != 0:
                if group.match(packages):
                    groups.append(group)
        return groups

    def __str__(self):
        return "%s: %d groups" % (self.__class__.__name__, len(self.groups.values()))


class YumGroup(object):
    def __init__(self, name, mandatory, default, optional):
        self.name = name
        self.mandatory = mandatory
        self.mandatory_set = set(mandatory)
        self.default = default
        self.optional = optional
        self.required = set(mandatory + default)

    def __str__(self):
        return "%s (%d required packages)" % (self.name, len(self.required))

    def __repr__(self):
        return "<%s: M:%s D:%s O:%s>" % (self.name, self.mandatory, self.default, self.optional)

    def match(self, packages):
        return self.required.issubset(packages)

    def exclude_mandatory(self, packages):
        return packages.difference(self.required)


class YumGroupGenerator(object):
    """class for aggregating packages into yum groups"""

    def __init__(self, package_list, removed_packages, *args, **kwargs):
        """
        we dont take info about groups from yum, but from dark matrix, format is:

        group_name | mandatory packages | default packages | optional

        package_list is a list of packages which should aggregated into groups
        args is a list of filepaths to files where group definitions are stored
        """
        self.packages = set(package_list)
        self.removed_packages = set(removed_packages)
        self.gm = YumGroupManager()
        self.group_def_fp = []
        for p in args:
            if os.path.exists(p):
                self.group_def_fp.append(p)
                self._read_group_info()

    def _read_group_info(self):
        def get_packages(s):
            # get rid of empty strings
            return [x for x in s.strip().split(',') if x]

        for fp in self.group_def_fp:
            lines = get_file_content(fp, 'r', True)
            for line in lines:
                stuff = line.split('|')
                name = stuff[0].strip()
                mandatory = get_packages(stuff[1])
                default = get_packages(stuff[2])
                optional = get_packages(stuff[3])
                # why would we want empty groups?
                if mandatory or default or optional:
                    yg = YumGroup(name, mandatory, default, optional)
                    self.gm.add(yg)

    def remove_packages(self, package_list):
        for pkg in self.removed_packages:
            if pkg in package_list:
                package_list.remove(pkg)
        return package_list

    def get_list(self):
        groups = self.gm.find_match(self.packages)
        output = []
        output_packages = self.packages
        for group in groups:
            if len(group.required) != 0:
                output.append('@' + group.name)
                output_packages = group.exclude_mandatory(output_packages)
        output.sort()
        output_packages = list(output_packages)
        output_packages.sort()
        return output + output_packages


class PackagesHandling(object):
    """class for replacing/updating package names"""

    def __init__(self, package_list, obsoleted, *args, **kwargs):
        """
        we dont take info about groups from yum, but from dark matrix, format is:

        group_name | mandatory packages | default packages | optional

        package_list is a list of packages which should aggregated into groups
        args is a list of filepaths to files where group definitions are stored
        """
        self.packages = package_list
        self.obsoleted = obsoleted

    def replace_obsolete(self):
        for pkg in self.obsoleted:
            fields = pkg.split()
            old_pkg = fields[0]
            new_pkg = fields[len(fields) - 1]
            self.packages = [new_pkg if x == old_pkg else x for x in self.packages]

    def get_packages(self):
        return self.packages