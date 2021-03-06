# # -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals
import os
import unittest
import shutil
import stat
import tempfile

from xml.etree import ElementTree
try:
    from xml.etree.ElementTree import ParseError
except ImportError:
    from xml.parsers.expat import ExpatError as ParseError

from preuputils.compose import ComposeXML
from preup import xccdf
from preup import settings
from preuputils import variables
from preuputils.xml_utils import XmlUtils
from preuputils.oscap_group_xml import OscapGroupXml
from preup.utils import write_to_file, get_file_content
from preup.xml_manager import html_escape, html_escape_string

import base


class TestXMLCompose(base.TestCase):

    """Tests of right composing of contents in groups."""

    def setUp(self):
        dir_name = os.path.join(os.getcwd(), 'tests', 'FOOBAR6_7')
        self.result_dir = os.path.join(dir_name+variables.result_prefix)
        dir_name = os.path.join(dir_name, 'dummy')
        if os.path.exists(self.result_dir):
            shutil.rmtree(self.result_dir)
        shutil.copytree(dir_name, self.result_dir)
        template_file = ComposeXML.get_template_file()
        self.tree = None
        try:
            self.tree = ElementTree.parse(template_file).getroot()
        except IOError:
            assert False

        settings.autocomplete = False
        self.target_tree = ComposeXML.run_compose(self.tree, self.result_dir)
        self.assertTrue(self.target_tree)

    def tearDown(self):
        shutil.rmtree(self.result_dir)

    def test_compose(self):
        """Basic test of composing"""
        expected_groups = ['failed', 'fixed', 'needs_action',
                           'needs_inspection', 'not_applicable', 'pass',
                           'unicode']

        generated_group = []
        for group in self.target_tree.findall(xccdf.XMLNS + "Group"):
            generated_group.append(group.get('id'))
        self.assertEqual(['xccdf_preupg_group_'+x for x in expected_groups], generated_group)

    def test_unicode_xml(self):
        """
        Test processing of non-ascii characters inside title and description
        sections.
        """
        u_title = u'Čekujeme unicode u hasičů'
        u_descr = u'Hoří horní heršpická hospoda Hrbatý hrozen.'
        uni_xml = os.path.join(self.result_dir, "unicode", "group.xml")
        try:
            # XML files should be always in utf-8!
            lines = [x.decode('utf-8') for x in get_file_content(uni_xml, "rb", True, False)]
        except IOError:
            assert False
        title = filter(lambda x: u_title in x, lines)
        descr = filter(lambda x: u_descr in x, lines)
        self.assertTrue(title, "title is wrong ecoded or missing")
        self.assertTrue(descr, "description is wrong encoded or missing")

    def test_unicode_script_author(self):
        """Test processing of non-ascii characters for author section"""
        u_author = b'Petr Stod\xc5\xaflka'.decode(settings.defenc)
        script_file = os.path.join(self.result_dir, "unicode", "dummy_unicode.sh")
        settings.autocomplete = True
        self.target_tree = ComposeXML.run_compose(self.tree, self.result_dir)
        self.assertTrue(self.target_tree)
        try:
            lines = get_file_content(script_file, "rb", True)
        except IOError:
            assert False
        author = filter(lambda x: u_author in x, lines)
        self.assertTrue(author)


class TestXML(base.TestCase):

    """Main testing of right generating of XML files for OSCAP."""

    def setUp(self):
        self.dirname = os.path.join("tests", "FOOBAR6_7" + variables.result_prefix, "test")
        if os.path.exists(self.dirname):
            shutil.rmtree(self.dirname)
        os.makedirs(self.dirname)
        self.filename = os.path.join(self.dirname, 'test.ini')
        self.rule = []
        self.test_solution = "test_solution.txt"
        self.check_script = "check_script.sh"
        self.loaded_ini = {}
        test_ini = {'content_title': 'Testing content title',
                    'content_description': ' some content description',
                    'author': 'test <test@redhat.com>',
                    'config_file': '/etc/named.conf',
                    'check_script': self.check_script,
                    'solution': self.test_solution,
                    'applies_to': 'test',
                    'requires': 'bash',
                    'binary_req': 'sed'}
        self.loaded_ini[self.filename] = []
        self.loaded_ini[self.filename].append(test_ini)
        self.check_sh = """#!/bin/bash

#END GENERATED SECTION

#This is testing check script
 """
        check_name = os.path.join(self.dirname, self.check_script)
        write_to_file(check_name, "wb", self.check_sh)
        os.chmod(check_name, stat.S_IEXEC | stat.S_IRWXG | stat.S_IRWXU)

        self.solution_text = """
A solution text for test suite"
"""
        test_solution_name = os.path.join(self.dirname, self.test_solution)
        write_to_file(test_solution_name, "wb", self.solution_text)
        os.chmod(check_name, stat.S_IEXEC | stat.S_IRWXG | stat.S_IRWXU)
        self.xml_utils = XmlUtils(self.dirname, self.loaded_ini)
        self.rule = self.xml_utils.prepare_sections()

    def tearDown(self):
        shutil.rmtree(self.dirname)
        if os.path.exists(os.path.join(os.getcwd(), 'migrate')):
            os.unlink(os.path.join(os.getcwd(), 'migrate'))
        if os.path.exists(os.path.join(os.getcwd(), 'upgrade')):
            os.unlink(os.path.join(os.getcwd(), 'upgrade'))

    def test_group_xml(self):
        """Basic test for whole program"""
        self.assertTrue(self.loaded_ini[self.filename])
        self.assertTrue(self.rule)

    def test_xml_rule_id(self):
        rule_id = filter(lambda x: '<Rule id="xccdf_preupg_rule_test_check_script" selected="true">' in x, self.rule)
        self.assertTrue(rule_id)

    def test_xml_profile_id(self):
        profile = filter(lambda x: '<Profile id="xccdf_preupg_profile_default">' in x, self.rule)
        self.assertTrue(profile)

    def test_xml_rule_title(self):
        rule_title = filter(lambda x: "<title>Testing content title</title>" in x, self.rule)
        self.assertTrue(rule_title)

    def test_xml_config_file(self):
        conf_file = filter(lambda x: "<xhtml:li>/etc/named.conf</xhtml:li>" in x, self.rule)
        self.assertTrue(conf_file)

    def test_xml_fix_text(self):
        fix_text = filter(lambda x: "<fixtext>_test_SOLUTION_MSG_TEXT</fixtext>" in x, self.rule)
        self.assertTrue(fix_text)

    def test_xml_solution_type_text(self):
        self.loaded_ini[self.filename][0]['solution_type'] = "text"
        self.xml_utils = XmlUtils(self.dirname, self.loaded_ini)
        self.rule = self.xml_utils.prepare_sections()
        fix_text = filter(lambda x: "<fixtext>_test_SOLUTION_MSG_TEXT</fixtext>" in x, self.rule)
        self.assertTrue(fix_text)

    def test_xml_solution_type_html(self):
        self.loaded_ini[self.filename][0]['solution_type'] = "html"
        self.xml_utils = XmlUtils(self.dirname, self.loaded_ini)
        self.rule = self.xml_utils.prepare_sections()
        fix_text = filter(lambda x: "<fixtext>_test_SOLUTION_MSG_HTML</fixtext>" in x, self.rule)
        self.assertTrue(fix_text)

    def test_check_script_author(self):
        self.rule = self.xml_utils.prepare_sections()
        lines = get_file_content(os.path.join(self.dirname, self.check_script), "rb", method=True)
        author = filter(lambda x: "test <test@redhat.com>" in x, lines)
        self.assertTrue(author)

    def test_xml_check_export_tmp_preupgrade(self):
        self.rule = self.xml_utils.prepare_sections()
        check_export = filter(lambda x: '<check-export export-name="TMP_PREUPGRADE" value-id="xccdf_preupg_value_test_check_script_state_tmp_preupgrade" />' in x, self.rule)
        self.assertTrue(check_export)

    def test_xml_current_directory(self):
        self.rule = self.xml_utils.prepare_sections()
        cur_directory = filter(lambda x: '<check-export export-name="CURRENT_DIRECTORY" value-id="xccdf_preupg_value_test_check_script_state_current_directory" />' in x, self.rule)
        self.assertTrue(cur_directory)

    def _create_temporary_dir(self):
        settings.UPGRADE_PATH = tempfile.mkdtemp()
        if os.path.exists(settings.UPGRADE_PATH):
            shutil.rmtree(settings.UPGRADE_PATH)
        os.makedirs(settings.UPGRADE_PATH)
        migrate = os.path.join(settings.UPGRADE_PATH, 'migrate')
        upgrade = os.path.join(settings.UPGRADE_PATH, 'upgrade')
        return migrate, upgrade

    def _delete_temporary_dir(self, migrate, upgrade):
        if os.path.exists(migrate):
            os.unlink(migrate)
        if os.path.exists(upgrade):
            os.unlink(upgrade)
        if os.path.exists(settings.UPGRADE_PATH):
            shutil.rmtree(settings.UPGRADE_PATH)

    def test_xml_migrate_not_upgrade(self):
        test_ini = {'content_title': 'Testing only migrate title',
                    'content_description': ' some content description',
                    'author': 'test <test@redhat.com>',
                    'config_file': '/etc/named.conf',
                    'check_script': self.check_script,
                    'solution': self.test_solution,
                    'applies_to': 'test',
                    'requires': 'bash',
                    'binary_req': 'sed',
                    'mode': 'migrate'}
        ini = {}
        old_settings = settings.UPGRADE_PATH
        migrate, upgrade = self._create_temporary_dir()
        ini[self.filename] = []
        ini[self.filename].append(test_ini)
        xml_utils = XmlUtils(self.dirname, ini)
        xml_utils.prepare_sections()
        migrate_file = get_file_content(migrate, 'rb', method=True)
        tag = [x.strip() for x in migrate_file if 'xccdf_preupg_rule_test_check_script' in x.strip()]
        self.assertIsNotNone(tag)
        try:
            upgrade_file = get_file_content(upgrade, 'rb', method=True)
        except IOError:
            upgrade_file = None
        self.assertIsNone(upgrade_file)
        self._delete_temporary_dir(migrate, upgrade)
        settings.UPGRADE_PATH = old_settings

    def test_xml_upgrade_not_migrate(self):
        test_ini = {'content_title': 'Testing only migrate title',
                    'content_description': ' some content description',
                    'author': 'test <test@redhat.com>',
                    'config_file': '/etc/named.conf',
                    'check_script': self.check_script,
                    'solution': self.test_solution,
                    'applies_to': 'test',
                    'requires': 'bash',
                    'binary_req': 'sed',
                    'mode': 'upgrade'}
        ini = {}
        old_settings = settings.UPGRADE_PATH
        migrate, upgrade = self._create_temporary_dir()
        ini[self.filename] = []
        ini[self.filename].append(test_ini)
        xml_utils = XmlUtils(self.dirname, ini)
        xml_utils.prepare_sections()
        upgrade_file = get_file_content(upgrade, 'rb', method=True)
        tag = [x.strip() for x in upgrade_file if 'xccdf_preupg_rule_test_check_script' in x.strip()]
        self.assertIsNotNone(tag)
        try:
            migrate_file = get_file_content(migrate, 'rb', method=True)
        except IOError:
            migrate_file = None
        self.assertIsNone(migrate_file)
        self._delete_temporary_dir(migrate, upgrade)
        settings.UPGRADE_PATH = old_settings

    def test_xml_migrate_and_upgrade(self):
        test_ini = {'content_title': 'Testing only migrate title',
                    'content_description': ' some content description',
                    'author': 'test <test@redhat.com>',
                    'config_file': '/etc/named.conf',
                    'check_script': self.check_script,
                    'solution': self.test_solution,
                    'applies_to': 'test',
                    'requires': 'bash',
                    'binary_req': 'sed',
                    'mode': 'migrate, upgrade'}
        ini = {}
        old_settings = settings.UPGRADE_PATH
        migrate, upgrade = self._create_temporary_dir()
        ini[self.filename] = []
        ini[self.filename].append(test_ini)
        xml_utils = XmlUtils(self.dirname, ini)
        xml_utils.prepare_sections()
        migrate_file = get_file_content(migrate, 'rb', method=True)
        tag = [x.strip() for x in migrate_file if 'xccdf_preupg_rule_test_check_script' in x.strip()]
        self.assertIsNotNone(tag)
        upgrade_file = get_file_content(upgrade, 'rb', method=True)
        tag = [x.strip() for x in upgrade_file if 'xccdf_preupg_rule_test_check_script' in x.strip()]
        self.assertIsNotNone(tag)
        self._delete_temporary_dir(migrate, upgrade)
        settings.UPGRADE_PATH = old_settings

    def test_xml_not_migrate_not_upgrade(self):
        test_ini = {'content_title': 'Testing only migrate title',
                    'content_description': ' some content description',
                    'author': 'test <test@redhat.com>',
                    'config_file': '/etc/named.conf',
                    'check_script': self.check_script,
                    'solution': self.test_solution,
                    'applies_to': 'test',
                    'requires': 'bash',
                    'binary_req': 'sed'}
        ini = {}
        old_settings = settings.UPGRADE_PATH
        migrate, upgrade = self._create_temporary_dir()
        ini[self.filename] = []
        ini[self.filename].append(test_ini)
        xml_utils = XmlUtils(self.dirname, ini)
        xml_utils.prepare_sections()
        migrate_file = get_file_content(migrate, 'rb', method=True)
        tag = [x.strip() for x in migrate_file if 'xccdf_preupg_rule_test_check_script' in x.strip()]
        self.assertIsNotNone(tag)
        upgrade_file = get_file_content(upgrade, 'rb', method=True)
        tag = [x.strip() for x in upgrade_file if 'xccdf_preupg_rule_test_check_script' in x.strip()]
        self.assertIsNotNone(tag)
        self._delete_temporary_dir(migrate, upgrade)
        settings.UPGRADE_PATH = old_settings

    def test_xml_check_script_reference(self):
        self.rule = self.xml_utils.prepare_sections()
        check_script_reference = filter(lambda x: '<check-content-ref href="check_script.sh" />' in x, self.rule)
        self.assertTrue(check_script_reference)

    def test_values_id(self):
        self.rule = self.xml_utils.prepare_sections()
        value_tmp_preupgrade = filter(lambda x: '<Value id="xccdf_preupg_value_test_check_script_state_tmp_preupgrade" operator="equals" type="string">' in x, self.rule)
        self.assertTrue(value_tmp_preupgrade)
        value_tmp_preupgrade_set = filter(lambda x: '<value>SCENARIO</value>' in x, self.rule)
        self.assertTrue(value_tmp_preupgrade_set)
        value_current_dir = filter(lambda x: '<Value id="xccdf_preupg_value_test_check_script_state_current_directory"' in x, self.rule)
        self.assertTrue(value_current_dir)
        value_current_dir_set = filter(lambda x: '<value>SCENARIO/test</value>' in x, self.rule)
        self.assertTrue(value_current_dir_set)

    def test_check_script_applies_to(self):
        self.rule = self.xml_utils.prepare_sections()
        lines = get_file_content(os.path.join(self.dirname, self.check_script), "rb", method=True)
        applies = filter(lambda x: 'check_applies_to "test"' in x, lines)
        self.assertTrue(applies)

    def test_check_script_common(self):
        self.rule = self.xml_utils.prepare_sections()
        lines = get_file_content(os.path.join(self.dirname, self.check_script), "rb", method=True)
        common = filter(lambda x: '. /usr/share/preupgrade/common.sh' in x, lines)
        self.assertTrue(common)

    def test_check_script_requires(self):
        self.rule = self.xml_utils.prepare_sections()
        lines = get_file_content(os.path.join(self.dirname, self.check_script), "rb", method=True)
        check_rpm_to = filter(lambda x: 'check_rpm_to "bash" "sed"' in x, lines)
        self.assertTrue(check_rpm_to)


class TestIncorrectINI(base.TestCase):

    """
    Tests right processing of INI files including incorrect input which
    could make for crash with traceback.
    """

    def setUp(self):
        self.dir_name = "tests/FOOBAR6_7/incorrect_ini"
        os.makedirs(self.dir_name)
        self.filename = os.path.join(self.dir_name, 'test.ini')
        self.rule = []
        self.test_solution = "test_solution.sh"
        self.check_script = "check_script.sh"
        self.loaded_ini = {}
        self.loaded_ini[self.filename] = []
        self.test_ini = {'content_title': 'Testing content title',
                    'content_description': 'Some content description',
                    'author': 'test <test@redhat.com>',
                    'config_file': '/etc/named.conf',
                    'check_script': self.check_script,
                    'solution': self.test_solution,
                    'applies_to': 'test'}
        solution_text = """
A solution text for test suite"
"""
        check_sh = """#!/bin/bash

#END GENERATED SECTION

#This is testing check script
 """
        write_to_file(os.path.join(self.dir_name, self.test_solution), "wb", solution_text)
        write_to_file(os.path.join(self.dir_name, self.check_script), "wb", check_sh)

    def tearDown(self):
        shutil.rmtree(self.dir_name)

    def test_missing_tag_check_script(self):
        """Basic test for whole program"""
        self.test_ini.pop('check_script', None)
        self.loaded_ini[self.filename].append(self.test_ini)
        self.xml_utils = XmlUtils(self.dir_name, self.loaded_ini)
        self.assertRaises(SystemExit, lambda: list(self.xml_utils.prepare_sections()))

    def test_missing_tag_solution_script(self):
        """Test of missing tag 'solution' - SystemExit should be raised"""
        self.test_ini.pop('solution', None)
        self.loaded_ini[self.filename].append(self.test_ini)
        self.xml_utils = XmlUtils(self.dir_name, self.loaded_ini)
        self.assertRaises(SystemExit, lambda: list(self.xml_utils.prepare_sections()))

    def test_file_solution_not_exists(self):
        """Test of missing 'solution' file - SystemExit should be raised"""
        self.test_ini['solution'] = "this_should_be_unexpected_file.txt"
        self.loaded_ini[self.filename].append(self.test_ini)
        self.xml_utils = XmlUtils(self.dir_name, self.loaded_ini)
        self.assertRaises(SystemExit, lambda: list(self.xml_utils.prepare_sections()))

    def test_file_check_script_not_exists(self):
        """Test of missing 'check_script' file"""
        self.test_ini['check_script'] = "this_should_be_unexpected_file.txt"
        self.loaded_ini[self.filename].append(self.test_ini)
        self.xml_utils = XmlUtils(self.dir_name, self.loaded_ini)
        self.assertRaises(SystemExit, lambda: list(self.xml_utils.prepare_sections()))

    def test_check_script_is_directory(self):
        """
        Directory as input instead of regular file is incorrect input
        Tests issue #29
        """
        self.test_ini['check_script'] = '.'
        self.loaded_ini[self.filename].append(self.test_ini)
        self.xml_utils = XmlUtils(self.dir_name, self.loaded_ini)
        self.assertRaises(SystemExit, lambda: list(self.xml_utils.prepare_sections()))

    def test_incorrect_tag(self):
        """
        Check occurrence of incorrect tag
        Tests issue #30
        """
        text_ini = '[preupgrade]\n'
        text_ini += '\n'.join([key + " = " + self.test_ini[key] for key in self.test_ini])
        text_ini += '\n[]\neliskk\n'
        write_to_file(self.filename, "wb", text_ini)
        oscap = OscapGroupXml(self.dir_name)
        self.assertRaises(SystemExit, oscap.find_all_ini)

    def test_secret_check_script(self):
        """Check occurrence of secret file for check script"""
        self.test_ini['check_script'] = '.minicheck'
        text = """#!/usr/bin/sh\necho 'ahojky'\n"""
        write_to_file(os.path.join(self.dir_name, self.check_script), "wb", text)
        self.loaded_ini[self.filename].append(self.test_ini)
        self.xml_utils = XmlUtils(self.dir_name, self.loaded_ini)
        self.assertRaises(SystemExit, lambda: list(self.xml_utils.prepare_sections()))


class TestGroupXML(base.TestCase):

    """Basic test for creating group.xml file"""

    #TODO: May should be deprecated and test could be moved under class TestXMLCompose

    def setUp(self):
        self.dir_name = "tests/FOOBAR6_7-results/test_group"
        os.makedirs(self.dir_name)
        self.filename = os.path.join(self.dir_name, 'group.ini')
        self.rule = []
        self.loaded_ini = {}
        test_ini = {'group_title': 'Testing content title'}
        self.assertTrue(test_ini)
        self.loaded_ini[self.filename] = []
        self.loaded_ini[self.filename].append(test_ini)

    def tearDown(self):
        shutil.rmtree(self.dir_name)

    def test_group_ini(self):
        """Basic test creation group.xml file"""
        self.xml_utils = XmlUtils(self.dir_name, self.loaded_ini)
        self.rule = self.xml_utils.prepare_sections()
        group_tag = filter(lambda x: '<Group id="xccdf_preupg_group_test_group" selected="true">' in x, self.rule)
        self.assertTrue(group_tag)
        title_tag = filter(lambda x: '<title>Testing content title</title>' in x, self.rule)
        self.assertTrue(title_tag)


class HTMLEscapeTest(base.TestCase):

    """Testing of right transform of unsafe characters to their entities"""

    def test_basic(self):
        """Basic test with quotation"""
        input_char = ['asd', '<qwe>', "this 'is' quoted"]
        output = html_escape(input_char)
        expected_output = ['asd', '&lt;qwe&gt;', 'this &apos;is&apos; quoted']
        self.assertEqual(output, expected_output)

    def test_basic_string(self):
        """Test if single string is escaped well"""
        input_char = "asd < > &"
        expected_output = "asd &lt; &gt; &amp;"
        output = html_escape_string(input_char)
        self.assertEqual(output, expected_output)

    def test_all(self):
        """Test if list of strings is escaped well"""
        tmp_input = ['a<', 'b>', "x'x", 'y"', 'z&z']
        output = html_escape(tmp_input)
        expected_ouput = ['a&lt;', 'b&gt;', 'x&apos;x', 'y&quot;', 'z&amp;z']
        self.assertEqual(output, expected_ouput)

    def test_amp_expand(self):
        """Test whether ampersand is not being expanded multiple times"""
        input_char = ['asd<>&']
        output = html_escape(input_char)
        expected_output = ['asd&lt;&gt;&amp;']
        self.assertEqual(output, expected_output)


class ComposeTest(base.TestCase):

    def setUp(self):
        pass

def suite():
    """Add classes which should be included in testing"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTest(loader.loadTestsFromTestCase(TestGroupXML))
    suite.addTest(loader.loadTestsFromTestCase(TestXML))
    suite.addTest(loader.loadTestsFromTestCase(TestIncorrectINI))
    suite.addTest(loader.loadTestsFromTestCase(TestXMLCompose))
    suite.addTest(loader.loadTestsFromTestCase(HTMLEscapeTest))
    return suite

if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=3).run(suite())
