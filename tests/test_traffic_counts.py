import unittest
from pathlib import Path

from traffic_counts import SheetError, parse_auto, parse_manual, peak_hour, sheet_names, street_token

MANUAL = """City Of Los Angeles
MANUAL TRAFFIC COUNT SUMMARY
North/South MAIN ST.
East/West 1st ST.
Hours:   7-10AM   3-6PM Chekrs: XX & YY
DUAL-
WHEELED 266 0 84 81
BIKES 41 0 37 32
BUSES 145 0 173 163
NORTHBOUND Approach SOUTHBOUND Approach TOTAL XING S/L XING N/L
Hours Lt Th Rt Total Hours Lt Th Rt Total N-S Ped Sch Ped Sch
8-9 87 852 80 1019 8-9 0 0 0 0 1019 325 0 151 0
5-6 198 2614 232 3044 5-6 0 0 0 0 3044 296 0 153 0
TOTAL 285 3466 312 4063 TOTAL 0 0 0 0 4063 621 0 304 0
EASTBOUND Approach WESTBOUND Approach TOTAL XING W/L XING E/L
Hours Lt Th Rt Total Hours Lt Th Rt Total E-W Ped Sch Ped Sch
8-9 130 636 0 766 8-9 0 587 101 688 1454 65 0 198 0
5-6 141 1032 0 1173 5-6 0 1255 159 1414 2587 112 0 254 0
TOTAL 271 1668 0 1939 TOTAL 0 1842 260 2102 4041 177 0 452 0
(Rev Oct 06)
November 8, 2011TUESDAY
"""

AUTO_ROWS = "\n".join(f"{h} {'AM' if i < 12 else 'PM'} 1 1 1 1 4 2 2 2 2 8 12" for i, h in enumerate(
    [12] + list(range(1, 12)) + [12] + list(range(1, 12))))
AUTO = f"""24 Hours Traffic Volume
Department of Transportation Date 03/11/14
Location CENTRAL AV AT 2 nd ST Day of Week TUESDAY Prepared 03/12/14
Direction N/S STREET DOT District CENTRAL By XX
{AUTO_ROWS}
24 HOUR VEHICLES TOTAL 96 192 288
"""


class SheetParsingTest(unittest.TestCase):
    def test_manual_sheet_reproduces_printed_totals(self):
        sheet = parse_manual(MANUAL)
        self.assertEqual(sheet["date"], "2011-11-08")
        self.assertEqual(sheet["approaches"]["nb"]["5-6"], {"left": 198, "through": 2614, "right": 232})
        self.assertEqual(sheet["pedestrians"]["east_leg"]["5-6"], 254)
        self.assertEqual(peak_hour(sheet, "pm"), "5-6")
        self.assertEqual(sheet["heavy_vehicles"]["buses"]["eb"], 173)
        self.assertNotIn("XX", repr(sheet), "count staff names are not stored")

    def test_manual_sheet_with_bad_totals_is_rejected(self):
        for broken in (MANUAL.replace("198 2614 232 3044", "198 2614 232 3045"),
                       MANUAL.replace("TOTAL 285 3466", "TOTAL 286 3466"),
                       MANUAL.replace("1019 325 0 151 0", "1020 325 0 151 0")):
            with self.assertRaises(SheetError):
                parse_manual(broken)

    def test_automatic_sheet_checks_hours_and_day(self):
        sheet = parse_auto(AUTO)
        self.assertEqual(sheet["daily"], {"nb": 96, "sb": 192, "total": 288})
        self.assertEqual(len(sheet["hourly"]["sb"]), 24)
        with self.assertRaises(SheetError):
            parse_auto(AUTO.replace("TOTAL 96 192 288", "TOTAL 97 192 288"))

    def test_navigatela_file_names(self):
        self.assertEqual(street_token("SAN PEDRO ST"), "SANPEDRO")
        self.assertEqual(street_token("1 st ST"), "1ST")
        self.assertEqual(sheet_names("1 st ST", "MAIN ST", "2011-11-08T00:00:00.000", "MAN"),
                         ["1ST.MAIN.111108-MAN.pdf", "MAIN.1ST.111108-MAN.pdf"])

    def test_cached_real_sheet_when_available(self):
        cache = Path(__file__).resolve().parents[1] / "private" / "discovery" / "sheets"
        if not (cache / "MAIN.1ST.111108-MAN.pdf").exists():
            self.skipTest("Official sheet not downloaded.")
        from traffic_counts import load_sheet
        sheet = load_sheet("MAIN.1ST.111108-MAN.pdf", cache)
        self.assertEqual(sum(sheet["approaches"]["wb"]["5-6"].values()), 1414)
        self.assertEqual(sheet["url"], "https://navigatela.lacity.org/dot/traffic_data/manual_counts/MAIN.1ST.111108-MAN.pdf")


if __name__ == "__main__":
    unittest.main()
