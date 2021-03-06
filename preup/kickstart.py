# -*- coding: utf-8 -*-

"""
Class creates a kickstart for migration scenario
"""

from __future__ import print_function, unicode_literals
import base64
import shutil
import os
import six

from pykickstart.parser import KickstartError, KickstartParser, Script
from pykickstart.version import makeVersion
from pykickstart.constants import KS_SCRIPT_POST, KS_SCRIPT_PRE, KS_MISSING_IGNORE
from preup.logger import log_message, logging
from preup import settings
from preup.utils import write_to_file, get_file_content
from preup import utils
from preup.kickstart_packages import YumGroupGenerator, PackagesHandling
from preup.kickstart_partitioning import PartitionGenerator


class KickstartGenerator(object):
    """Generate kickstart using data from provided result"""
    def __init__(self, dir_name, kick_start_name):
        self.dir_name = dir_name
        self.ks = None
        self.kick_start_name = kick_start_name
        self.ks_list = []
        self.part_layout = ['clearpart --all']
        self.repos = None
        self.users = None
        self.latest_tarball = ""
        self.temp_file = '/tmp/part-include'

    def collect_data(self):
        collected_data = True
        self.ks = KickstartGenerator.load_or_default(KickstartGenerator.get_kickstart_path(self.dir_name))
        if self.ks is None:
            collected_data = False
        self.repos = KickstartGenerator.get_kickstart_repo('available-repos')
        self.users = KickstartGenerator.get_kickstart_users('Users')
        self.latest_tarball = self.get_latest_tarball()
        return collected_data

    @staticmethod
    def get_kickstart_path(dir_name):
        return os.path.join(dir_name, 'anaconda-ks.cfg')

    @staticmethod
    def load_or_default(system_ks_path):
        """load system ks or default ks"""
        ksparser = KickstartParser(makeVersion())
        try:
            ksparser.readKickstart(system_ks_path)
        except (KickstartError, IOError):
            log_message("Can't read system kickstart at {0}".format(system_ks_path))
            try:
                ksparser.readKickstart(settings.KS_TEMPLATE)
            except AttributeError:
                log_message("There is no KS_TEMPLATE_POSTSCRIPT specified in settings.py")
            except IOError:
                log_message("Can't read kickstart template {0}".format(settings.KS_TEMPLATE))
                return None
        return ksparser

    @staticmethod
    def get_package_list(filename):
        """
        content packages/ReplacedPackages is taking care of packages, which were
        replaced/obsoleted/removed between releases. It produces a file with a list
        of packages which should be installed.
        """
        lines = get_file_content(os.path.join(settings.KS_DIR, filename), 'rb', method=True)
        # Remove newline character from list
        lines = [line.strip() for line in lines]
        return lines

    @staticmethod
    def get_kickstart_repo(filename):
        """
        returns dictionary with names and URLs
        :param filename: filename with available-repos
        :return: dictionary with enabled repolist
        """
        try:
            lines = get_file_content(os.path.join(settings.KS_DIR, filename), 'rb', method=True)
        except IOError:
            return None
        lines = [x for x in lines if not x.startswith('#') and not x.startswith(' ')]
        if not lines:
            return None
        repo_dict = {}
        for line in lines:
            fields = line.split('=')
            repo_dict[fields[0]] = fields[2]
        return repo_dict

    @staticmethod
    def get_kickstart_users(filename, splitter=":"):
        """
        returns dictionary with names and uid, gid, etc.
        :param filename: filename with Users in /root/preupgrade/kickstart directory
        :return: dictionary with users
        """
        try:
            lines = get_file_content(os.path.join(settings.KS_DIR, filename), 'rb', method=True)
        except IOError:
            return None
        lines = [x for x in lines if not x.startswith('#') and not x.startswith(' ')]
        user_dict = {}
        for line in lines:
            fields = line.split(splitter)
            try:
                user_dict[fields[0]] = "%s:%s" % (fields[2], fields[3])
            except IndexError:
                pass
        return user_dict

    @staticmethod
    def _get_sizes(filename):
        part_sizes = {}
        lines = get_file_content(os.path.join(settings.KS_DIR, filename), 'rb', method=True, decode_flag=False)
        lines = [x for x in lines if x.startswith('/')]
        for line in lines:
            fields = line.strip().split(' ')
            part_name = fields[0]
            try:
                size = fields[2]
            except IndexError:
                size = fields[1]
            part_sizes[part_name] = size
        return part_sizes

    def output_packages(self):
        """outputs %packages section"""
        try:
            installed_packages = KickstartGenerator.get_package_list('PA_RHRHEL7rpmlist')
            # We need only package names
            installed_packages = [i.split()[0] for i in installed_packages]
        except IOError:
            return None
        try:
            obsoleted = KickstartGenerator.get_package_list('RHRHEL7rpmlist_obsoleted-required')
        except IOError:
            obsoleted = []
        ph = PackagesHandling(installed_packages, obsoleted)
        # remove files which are replaced by another package
        ph.replace_obsolete()

        if os.path.exists(os.path.join(settings.KS_DIR, 'RemovedPkg-optional')):
            try:
                removed_packages = KickstartGenerator.get_package_list('RemovedPkg-optional')
            except IOError:
                return None
        # TODO We should think about if ObsoletedPkg-{required,optional} should be used
        if not installed_packages or not removed_packages:
            return None
        abs_fps = [os.path.join(settings.KS_DIR, fp) for fp in settings.KS_FILES]
        ygg = YumGroupGenerator(ph.get_packages(), removed_packages, *abs_fps)
        display_package_names = ygg.get_list()
        display_package_names = ygg.remove_packages(display_package_names)
        return display_package_names

    def delete_obsolete_issues(self):
        """ Remove obsolete items which does not exist on RHEL-7 anymore"""
        self.ks.handler.bootloader.location = None

    def embed_script(self, tarball):
        tarball_content = get_file_content(tarball, 'rb', decode_flag=False)
        tarball_name = os.path.splitext(os.path.splitext(os.path.basename(tarball))[0])[0]
        script_str = ''
        try:
            script_path = settings.KS_TEMPLATE_POSTSCRIPT
        except AttributeError:
            log_message('KS_TEMPLATE_POSTSCRIPT is not defined in settings.py')
            return
        script_str = get_file_content(os.path.join(settings.KS_DIR, script_path), 'rb')
        if not script_str:
            log_message("Can't open script template: {0}".format(script_path))
            return

        script_str = script_str.replace('{tar_ball}', base64.b64encode(tarball_content))
        script_str = script_str.replace('{RESULT_NAME}', tarball_name)

        script = Script(script_str, type=KS_SCRIPT_POST, inChroot=True)
        self.ks.handler.scripts.append(script)

    def save_kickstart(self):
        kickstart_data = self.ks.handler.__str__()
        kickstart_data = kickstart_data.replace('%pre', '%%include %s\n\n%%pre\n' % self.temp_file)
        write_to_file(self.kick_start_name, 'wb', kickstart_data)

    def update_kickstart(self, text, cnt):
        self.ks_list.insert(cnt, text)
        return cnt + 1

    @staticmethod
    def copy_kickstart_templates():
        # Copy kickstart files (/usr/share/preupgrade/kickstart) for kickstart generation
        for file_name in settings.KS_TEMPLATES:
            target_name = os.path.join(settings.KS_DIR, file_name)
            source_name = os.path.join(settings.source_dir, 'kickstart', file_name)
            if not os.path.exists(target_name) and os.path.exists(source_name):
                try:
                    shutil.copy(source_name, target_name)
                except IOError:
                    log_message("Copying %s to %s failed" % (source_name, target_name))
                    pass

    @staticmethod
    def get_volume_info(filename, first_index, second_index):
        try:
            volume_list = get_file_content(os.path.join(settings.KS_DIR, filename), 'rb', method=True, decode_flag=False)
        except IOError:
            log_message("File %s is missing. Partitioning layout has not to be complete." % filename, level=logging.WARNING)
            return None
        volume_info = {}
        for line in volume_list:
            fields = line.strip().split(':')
            volume_info[fields[first_index]] = fields[second_index]
        return volume_info

    def update_repositories(self, repositories):
        if repositories:
            for key, value in six.iteritems(repositories):
                self.ks.handler.repo.dataList().append(self.ks.handler.RepoData(name=key, baseurl=value.strip()))

    def update_users(self, users):
        if not users:
            return None
        for key, value in users.iteritems():
            uid, gid = value
            self.ks.handler.user.dataList().append(self.ks.handler.UserData(name=key, uid=int(uid), groups=[gid]))

    def get_partition_layout(self, lsblk, vgs, lvdisplay):
        """
        Returns dictionary with partition and realname and size
        :param filename:  filename with partition_layout in /root/preupgrade/kickstart directory
        :return: dictionary with layout
        """
        lsblk_filename = os.path.join(settings.KS_DIR, lsblk)
        try:
            layout = get_file_content(lsblk_filename, 'rb', method=True, decode_flag=False)
        except IOError:
            log_message("File %s was not generated by a content. Kickstart does not contain partitioning layout" % lsblk_filename)
            self.part_layout = None
            return None
        vg_info = []
        lv_info = []
        if vgs is not None:
            vg_info = KickstartGenerator.get_volume_info(vgs, 0, 5)
        if lvdisplay is not None:
            lv_info = KickstartGenerator.get_volume_info(lvdisplay, 0, 1)
        pg = PartitionGenerator(layout, vg_info, lv_info)
        pg.generate_partitioning()
        self.part_layout.extend(pg.get_partitioning())

    def update_partitioning(self):
        if self.part_layout is None:
            return

        # Index 1 means size
        script_str = ['echo "# This is partition layout generated by preupg --kickstart command" > %s' % self.temp_file]
        script_str.extend(['echo "%s" >> %s' % (line, self.temp_file) for line in self.part_layout])
        script = Script('\n'.join(script_str), type=KS_SCRIPT_PRE, inChroot=True)
        self.ks.handler.scripts.append(script)

    def get_prefix(self):
        return settings.tarball_prefix + settings.tarball_base

    def get_latest_tarball(self):
        tarball = None
        for directories, dummy_subdir, filenames in os.walk(settings.tarball_result_dir):
            preupg_files = [x for x in sorted(filenames) if x.startswith(self.get_prefix())]
            # We need a last file
            tarball = os.path.join(directories, preupg_files[-1])
        return tarball

    def filter_kickstart_users(self):
        kickstart_users = {}
        if not self.users:
            return None
        setup_passwd = KickstartGenerator.get_kickstart_users('setup_passwd')
        uidgid = KickstartGenerator.get_kickstart_users('uidgid', splitter='|')
        for user, ids in six.iteritems(self.users):
            if setup_passwd:
                if [x for x in six.iterkeys(setup_passwd) if user in x]:
                    continue
            if uidgid:
                if [x for x in six.iterkeys(uidgid) if user in x]:
                    continue
            kickstart_users[user] = ids.split(':')
        if not kickstart_users:
            return None
        return kickstart_users

    def generate(self):
        if not self.collect_data():
            log_message("Important data are missing for kickstart generation.", level=logging.ERROR)
            return None
        packages = self.output_packages()
        if packages:
            self.ks.handler.packages.add(packages)
        self.ks.handler.packages.handleMissing = KS_MISSING_IGNORE
        self.update_repositories(self.repos)
        self.update_users(self.filter_kickstart_users())
        self.get_partition_layout('lsblk_list', 'vgs_list', 'lvdisplay')
        self.update_partitioning()
        self.embed_script(self.latest_tarball)
        self.delete_obsolete_issues()
        self.save_kickstart()
        return True

    @staticmethod
    def kickstart_scripts():
        try:
            lines = utils.get_file_content(os.path.join(settings.common_dir,
                                                        settings.KS_SCRIPTS),
                                           "rb",
                                           method=True)
            for counter, line in enumerate(lines):
                line = line.strip()
                if line.startswith("#"):
                    continue
                if 'is not installed' in line:
                    continue
                cmd, name = line.split("=", 2)
                kickstart_file = os.path.join(settings.KS_DIR, name)
                utils.run_subprocess(cmd, output=kickstart_file, shell=True)
        except IOError:
            pass


def main():
    kg = KickstartGenerator()
    #print kg.generate()

    # group.packages() -> ['package', ...]
    #import ipdb ; ipdb.set_trace()
    return

if __name__ == '__main__':
    main()
