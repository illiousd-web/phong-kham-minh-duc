"""Convert the two project-approved public workbooks, validating their exact counts."""
import csv
import hashlib
from pathlib import Path

from app.patient_catalog import DATA, CSV_GEO_HEADERS, ETHNIC_HEADERS, parse_geography, parse_ethnicities

GEO = 'Danh-muc-Phuong-xa_moi_34-tinh-thanh-sau-sat-nhap.xlsx'
ETHNIC = 'Danh_sach_54_dan_toc_Viet_Nam_2026.xlsx'


def build():
    geo = parse_geography((DATA/GEO).read_bytes(), GEO, bundled=True)
    ethnics = parse_ethnicities((DATA/ETHNIC).read_bytes(), ETHNIC, bundled=True)
    provinces = {row[1]: row[2] for row in geo if row[0]=='province'}
    with (DATA/'tinh_xa.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.writer(handle,lineterminator='\n');writer.writerow(CSV_GEO_HEADERS)
        for row in geo:
            if row[0]=='commune':writer.writerow([row[3],provinces[row[3]],row[1],row[2],row[5],row[6],row[7] or ''])
    with (DATA/'dan_toc.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.writer(handle,lineterminator='\n');writer.writerow(ETHNIC_HEADERS)
        for row in ethnics:
            if row[1] not in ('FOREIGN','UNKNOWN'):writer.writerow([row[1],row[2],row[4]])
    for name in (GEO,ETHNIC,'tinh_xa.csv','dan_toc.csv'):
        print(hashlib.sha256((DATA/name).read_bytes()).hexdigest()+'  '+name)


if __name__=='__main__':build()
