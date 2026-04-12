from app import app
from database.db import get_patient_history, get_patient_record

patient_id = 1
history = get_patient_history(patient_id, limit=1)
print('history entry:', history[0] if history else 'none')

if history:
    record_id = history[0]['id']
    record = get_patient_record(record_id)
    print('record from get_patient_record:', record)

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = patient_id
            sess['role'] = 'patient'
        res = c.get(f'/generate-report/{record_id}')
        print('status', res.status_code)
        if res.status_code != 200:
            print('data', res.get_data(as_text=True))
        else:
            print('pdf', res.headers.get('Content-Type'), len(res.get_data()))
