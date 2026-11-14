import unittest
from pydantic import ValidationError
from proposal import Proposal, fixture
from site_measurements import projected

class ProposalTest(unittest.TestCase):
    def test_geometry_and_metrics_match_each_revision(self):
        for workflow in ('street', 'water'):
            first = fixture(-118.25313,34.03758,workflow,'site',1)
            second = fixture(-118.25313,34.03758,workflow,'site',2)
            self.assertNotEqual(first.input_hash,second.input_hash)
            for p in (first,second):
                area = projected(p.geometry[0].geometry).area
                self.assertAlmostEqual(area,p.metrics[0].proposed,places=4)
                self.assertIsNone(p.metrics[1].proposed)
                self.assertTrue(p.development_fixture)
                self.assertEqual(p.overlap.status,'unassessed')

    def test_contract_rejects_mixed_revisions_and_unassessed_values(self):
        original=fixture(-118.25313,34.03758,'street','site').model_dump(mode='json')
        for mutate in (
            lambda p:p['metrics'][0].update(revision=2),
            lambda p:p['metrics'][0].update(input_hash='old'),
            lambda p:p['geometry'][0]['properties'].update(revision=2),
            lambda p:p['metrics'][1].update(proposed=0),
            lambda p:p.update(proposed_geometry_ids=['missing']),
        ):
            import copy
            changed=copy.deepcopy(original);mutate(changed)
            with self.assertRaises(ValidationError): Proposal.model_validate(changed)

    def test_invalid_location_and_revision(self):
        for lon,lat,workflow,revision in [(float('nan'),34,'street',1),(-118,34,'street',1),(-118.25,34,'wrong',1),(-118.25,34,'water',0)]:
            with self.assertRaises(ValueError): fixture(lon,lat,workflow,'site',revision)

if __name__=='__main__': unittest.main()
