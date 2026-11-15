import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from server import Handler, coverage, nearby_frontages, property_catalog, reported_total


class ServerDataTest(unittest.TestCase):
    def test_partial_invalid_and_boolean_counts_never_become_complete_totals(self):
        self.assertEqual(reported_total([0, 5]), 5)
        for values in ([], [25, None], [True, 1], [-1, 1], [1.5, 1], ['25'], [float('nan')]):
            self.assertIsNone(reported_total(values))

    def test_catalog_preserves_incomplete_frontages_and_unknown_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'schemas').mkdir(); (root/'data').mkdir()
            (root/'schemas/enums.json').write_text(json.dumps({'PropertyType':{'1':'Office'}}))
            record={'id':1,'propertyType':1,'primaryAddress':{'latitude':34.05,'longitude':-118.25},
                    'parking':[{'totalSpaces':25},{}], 'grossBuildingAreaSquareFeet':True,
                    'propertyApartment':{'totalNumUnits':True},
                    'propertyRetail':{'numExternalLoadingDocks':2,'frontage':[{'numCurbCuts':1}]}}
            path=root/'data/commercial-property.jsonl'; path.write_text(json.dumps(record)+'\n')
            property_catalog.cache_clear()
            try:
                with patch.dict('os.environ',{'COSTAR_KIT_DIR':directory}):
                    _,details,frontages=property_catalog()
                    for key in ('reportedParkingSpaces','reportedLoadingDocks','units','buildingAreaSqFt'):
                        self.assertIsNone(details['1'][key])
                    self.assertIsNone(frontages['1'][0]['geometry'])
                    property_catalog.cache_clear()
                    path.write_text((json.dumps(record)+'\n')*2)
                    with self.assertRaisesRegex(ValueError,'duplicated'): property_catalog()
                    for invalid_id in (None, True, {}, 0, -1, " "):
                        property_catalog.cache_clear()
                        path.write_text(json.dumps({**record,'id':invalid_id})+'\n')
                        with self.assertRaisesRegex(ValueError,'identity'): property_catalog()
            finally: property_catalog.cache_clear()

    def test_nearby_frontages_do_not_drop_thirteenth_constraint(self):
        records=[{'id':'1','lat':34.05,'lon':-118.25}]
        lines=[{'geometry':{'type':'LineString','coordinates':[]},'curbCuts':n} for n in range(13)]
        with patch('server.property_catalog',return_value=(records,{}, {'1':lines})):
            result=nearby_frontages(-118.25,34.05,'1')
        self.assertEqual(len(result),13)
        self.assertEqual(result[-1]['curbCuts'],12)

    def test_source_errors_do_not_expose_paths_and_disconnect_does_not_send_twice(self):
        h=Handler.__new__(Handler);h.path='/api/search?q=test';h.send_json=Mock()
        with patch('server.property_catalog',side_effect=FileNotFoundError('PRIVATE KIT PATH')):h.do_GET()
        self.assertEqual(h.send_json.call_args.args[0],503)
        self.assertNotIn('PRIVATE',str(h.send_json.call_args))
        h.path='/api/tiles/12/1/1.jpg';h.send=Mock(side_effect=BrokenPipeError());h.send_json.reset_mock()
        with patch('server.tile',return_value=b'jpeg'):h.do_GET()
        h.send.assert_called_once();h.send_json.assert_not_called()

    def test_coverage_rejects_missing_or_nonpolygon_geometry(self):
        crossed = {'type':'Polygon','coordinates':[[[-118.3,34],[-118.2,34.1],[-118.3,34.1],[-118.2,34],[-118.3,34]]]}
        for geometry in (None,{'type':'Point','coordinates':[-118.25,34.05]}, {'type':'Polygon','coordinates':[]},{'type':'Polygon'},crossed):
            with patch('server._coverage',None),patch('server.vexcel_request',return_value=json.dumps({'features':[{'geometry':geometry}]}).encode()):
                with self.assertRaises(ValueError):coverage()

    def test_malformed_collection_does_not_remove_other_source_coverage(self):
        valid = {'type':'Polygon','coordinates':[[[-118.3,34],[-118.2,34],[-118.2,34.1],[-118.3,34.1],[-118.3,34]]]}
        crossed = {'type':'Polygon','coordinates':[[[-118.5,34],[-118.4,34.1],[-118.5,34.1],[-118.4,34],[-118.5,34]]]}
        payload = {'features':[{'geometry':crossed},{'geometry':valid},None,{'geometry':{'type':'Polygon'}}]}
        with patch('server._coverage',None),patch('server.vexcel_request',return_value=json.dumps(payload).encode()) as request:
            result = coverage()
            self.assertEqual([f['geometry'] for f in result['features']],[valid])
            self.assertEqual(result['status'],'partial')
            self.assertEqual(result['excludedFeatures'],3)
            self.assertEqual(coverage(),result)
            request.assert_called_once()


if __name__=='__main__':unittest.main()
