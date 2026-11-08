"""Read-only capacity report; no patient filenames, credentials or deletion."""
import json
import os
from pathlib import Path
from app.config import DATA,DATABASE_URL,LAN
from app.resources import LIMITS
from app.storage import tree_bytes,free_bytes


def status():
    paths={'attachments':Path(os.getenv('CLINIC_UPLOAD_DIR',str(DATA/'attachments'))),
           'application_logs':DATA/'logs','backups':Path(os.getenv('CLINIC_BACKUP_DIR',str(DATA/'backups')))}
    pg_logs=os.getenv('CLINIC_PG_LOG_DIR')
    if pg_logs:paths['postgres_logs']=Path(pg_logs)
    result={'synthetic_pilot_only':True,'free_data_mib':round(free_bytes(DATA)/1048576),
            'minimum_free_mib':LIMITS.min_free_bytes//1048576,
            'usage_mib':{key:round(tree_bytes(path)/1048576,2) for key,path in paths.items()},
            'attachment_limit_mib':LIMITS.upload_total_bytes//1048576,
            'backup_budget_mib':LIMITS.backup_total_bytes//1048576}
    result['warnings']=[]
    if result['free_data_mib']<20480:result['warnings'].append('LOW_DISK_SPACE_STOP_NEW_WRITES')
    if result['usage_mib']['attachments']>=result['attachment_limit_mib']*.8:result['warnings'].append('ATTACHMENTS_80_PERCENT')
    if result['usage_mib']['backups']>=result['backup_budget_mib']*.8:result['warnings'].append('BACKUPS_80_PERCENT')
    if result['usage_mib'].get('postgres_logs',0)>1024:result['warnings'].append('POSTGRES_LOGS_OVER_1_GIB')
    if LAN:
        import psycopg
        with psycopg.connect(DATABASE_URL) as c:
            c.execute('SET TRANSACTION READ ONLY')
            result['database_mib']=round(c.execute('SELECT pg_database_size(current_database())').fetchone()[0]/1048576,2)
            result['database_connections']=c.execute('SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()').fetchone()[0]
    return result


def main():print(json.dumps(status(),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
