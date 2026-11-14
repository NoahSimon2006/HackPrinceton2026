import unittest
from server import analysis_identity


class AnalysisIdentityTest(unittest.TestCase):
    def test_request_identity_is_required_and_rejects_coerced_versions(self):
        payload = {'siteId':'site:34.05:-118.25','proposalRevision':2,'inputRevision':1}
        self.assertEqual(analysis_identity(payload),{'site_id':payload['siteId'],'revision':2,'input_revision':1})
        for change in ({'siteId':''},{'siteId':None},{'proposalRevision':True},{'proposalRevision':1.5},
                       {'proposalRevision':0},{'proposalRevision':101},{'inputRevision':-1},{'inputRevision':'1'}):
            with self.assertRaises(ValueError):analysis_identity({**payload,**change})
        with self.assertRaises(ValueError):analysis_identity({})
