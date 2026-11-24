import pathlib
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]


class StandalonePreparationBuildContractTests(unittest.TestCase):
    def test_interaction_instance_matches_python_and_injector(self):
        source = (ROOT / 'university_class_preparation.py').read_text(encoding='utf-8')
        interaction = ET.parse(str(ROOT / 'tuning-preparation' / 'UCP_SePrepararParaAula.xml')).getroot()
        snippet = ET.parse(str(ROOT / 'tuning-preparation' / 'UCP_SePrepararParaAula_XmlInjector.xml')).getroot()

        python_id = re.search(r'^INTERACTION_ID\s*=\s*(\d+)$', source, re.MULTILINE)
        self.assertIsNotNone(python_id)
        interaction_id = interaction.attrib['s']
        injected_id = snippet.find('.//L[@n="_super_affordances"]/T').text
        self.assertEqual(python_id.group(1), interaction_id)
        self.assertEqual(interaction_id, injected_id)

    def test_tuning_points_to_standalone_module_and_class(self):
        interaction = ET.parse(str(ROOT / 'tuning-preparation' / 'UCP_SePrepararParaAula.xml')).getroot()
        self.assertEqual(interaction.attrib['m'], 'university_class_preparation')
        self.assertEqual(interaction.attrib['c'], 'SePrepararParaAulaInteraction')

    def test_xml_injector_targets_mailbox_tunings(self):
        snippet = ET.parse(str(ROOT / 'tuning-preparation' / 'UCP_SePrepararParaAula_XmlInjector.xml')).getroot()
        selector = snippet.find('.//T[@n="partial_name"]')
        self.assertIsNotNone(selector)
        self.assertEqual(selector.text, 'object_Mailbox')

    def test_script_compiles(self):
        source = ROOT / 'university_class_preparation.py'
        compile(source.read_text(encoding='utf-8'), str(source), 'exec')


if __name__ == '__main__':
    unittest.main()
