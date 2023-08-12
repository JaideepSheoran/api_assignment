import copy
from unittest import result
from flask import Flask, jsonify, make_response, render_template, redirect, request, Blueprint, session
from functools import cmp_to_key, wraps
from flask_cors import CORS
from flask_pymongo import ObjectId, PyMongo
from firebase_admin import credentials, initialize_app, firestore, storage
import jwt
from datetime import datetime, timedelta
from pytz import timezone


app = Flask(__name__, template_folder='templates')
CORS(app)
app.config['MONGO_URI'] =  "mongodb+srv://jaideepsinghsheoran:jaideep123@cluster0.sme0l7z.mongodb.net/storemanager"
app.config['SECRET_KEY'] = "jaideepsinghsheoranisbacktobuisness"
mongo_db = PyMongo(app).db

# Initialize Firestore DB
cred = credentials.Certificate('key.json')
default_app = initialize_app(cred)
db = firestore.client()
cloud_bucket = storage.bucket("maze-fca2f.appspot.com")






def convert_utc_to_local_timezone(timestamp_utc, time_zone):
    return datetime.astimezone(timestamp_utc ,timezone(time_zone))


def get_week_day(localtime):
    return datetime.weekday(localtime)


def convert_polling_time_to_local_time(store_status, time_zone):

    polling = []

    for store in store_status:
        utc_time = store['timestamp_utc']
        status = store['status']
        local_time = convert_utc_to_local_timezone(timestamp_utc=utc_time, time_zone=time_zone)
        polling.append({'local_time' : local_time, 'status' : status})

    return polling



def map_localtime_to_weekdays(polling_time):

    week_map = {
        0 : [],
        1 : [],
        2 : [],
        3 : [],
        4 : [],
        5 : [],
        6 : []
    }

    for local_time in polling_time:
        week_day = get_week_day(localtime=local_time['local_time'])
        local_time_str = str(local_time['local_time'].strftime("%H:%M:%S"))
        (hr, spr, rem) = local_time_str.partition(':')
        (mn, spr, sec) = rem.partition(':')
        week_map[week_day].append({'poll_time' : timedelta(hours=int(hr), minutes=int(mn), seconds=int(sec)), 'status' : local_time['status']})


    def compare(a):
        return a['poll_time']
    

    for key, value in week_map.items():
        week_map[key].sort(key=compare)

    return week_map

    

def downtime_uptime(store_status, opening_time, time_zone):


    local_polling_time = convert_polling_time_to_local_time(store_status=store_status, time_zone=time_zone)
    week_dict = map_localtime_to_weekdays(local_polling_time)

    rest_timing = {
        0 : [],
        1 : [],
        2 : [],
        3 : [],
        4 : [],
        5 : [],
        6 : []
    }


    for timing in opening_time:
        day = timing['day']
        start_time = timing['start_time_local']
        end_time = timing['end_time_local']

        (hr, spr, rem) = start_time.partition(':')
        (mn, spr, sec) = rem.partition(':')

        (hr_, spr_, rem_) = end_time.partition(':')
        (mn_, spr_, sec_) = rem_.partition(':')

        rest_timing[day].append(timedelta(hours=int(hr), minutes=int(mn), seconds=int(sec)))
        rest_timing[day].append(timedelta(hours=int(hr_), minutes=int(mn_), seconds=int(sec_)))

    
    for i in range(0, 7):
        if len(rest_timing[i]) == 0:
            rest_timing[i].append(timedelta(hours=0, minutes=0, seconds=0))
            rest_timing[i].append(timedelta(hours=23, minutes=59, seconds=59))


    result = [None]*7

    for day in range(0, 7):
        downtime_minutes = timedelta(hours=0, minutes=0, seconds=0)
        start = rest_timing[day][0]
        end = rest_timing[day][1]
        poll = week_dict[day]


        i = 0


        while i < len(poll):
            if start >= poll[i]['poll_time']:
                i += 1
                continue

            if poll[i]['poll_time'] > end:
                break

            if poll[i]['status'] == 'inactive':
                downtime_minutes += (poll[i]['poll_time'] - start)

            start = poll[i]['poll_time']

            i += 1



        if i - 1 >= 0 and poll[i - 1]['poll_time'] < end and start <= poll[i - 1]['poll_time']:
            if poll[i - 1]['status'] == 'inactive':
                downtime_minutes += (end - poll[i - 1]['poll_time'])


        uptime_minutes = rest_timing[day][1] - rest_timing[day][0] - downtime_minutes
        result[day] = [uptime_minutes.total_seconds(), downtime_minutes.total_seconds()]


    return result




@app.route('/trigger_report/<int:store_id>')
def generate_report(store_id):
    # if not store_id
    if store_id is None:
        return make_response({'message' : "Enter Store ID"}, 404)
    

    # store polling data
    store_status = mongo_db.store_status.find({'store_id' : store_id}).sort("timestamp_utc")

    if store_status is None:
        return make_response({'message' : 'Not found store_id'}, 404)

    # store opening status
    opening_time = mongo_db.menu_hours.find({'store_id': store_id})

    # get time zone of store
    time_zone = mongo_db.time_zone.find_one({'store_id' : store_id})

    if time_zone is None:
        time_zone = 'America/Chicago'
    else:
        time_zone = time_zone['timezone_str']

    
    result = downtime_uptime(store_status=store_status, opening_time=opening_time, time_zone=time_zone)

    return make_response(jsonify(result), 200)














# Login Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        if request.cookies.get('access_token'):
            token = request.cookies.get('access_token')
        if not token:
            return redirect('/login')
        
        try:
            user_id = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            print(user_id)
        except:
            return make_response(jsonify({"message" : "Invalid Token"}), 401)

        return f(*args, **kwargs)
    return decorated_function


# Login method responsible for generating authentication tokens
@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        userDetails = {
            'email' : request.form.get('email'),
            'password' : request.form.get('password')
        }
        
        user = mongo_db.users.find_one({'email' : userDetails['email'], 'password' : userDetails['password']})


        if not user:
            return make_response('Create Account, Email Not Present.', 401)

        access_token = jwt.encode({'email': user['email'], 'city' : user['city']}, app.config['SECRET_KEY'], algorithm='HS256')

        resp = make_response(jsonify({"access_token" : access_token}), 201)
        resp.set_cookie('access_token', access_token, max_age=1000000, httponly=True, secure=True, samesite=None)
        return resp
    else:
        return render_template('login.html')
    


# Login method responsible for generating authentication tokens
@app.route('/signup', methods=['POST', 'GET'])
def signup():
    if request.method == 'POST':
        userDetails = {
            'email' : request.form.get('email'),
            'fullname' : request.form.get('fullname'),
            'password' : request.form.get('password'),
            'education' : request.form.get('education'),
            'contact' : request.form.get('phone'),
            'city' : request.form.get('city')
        }

        if len(userDetails['contact']) != 10 or len(userDetails['password']) <= 6 or userDetails['password'] == "" or userDetails['fullname'] == "" or userDetails['email'] == "" :
            return redirect('/signup')

        
        user = mongo_db.users.find_one({'email' : userDetails['email']})

        if user:
            return make_response('Already Present !!! Please Login', 401)

        try:
            mongo_db.users.insert_one(userDetails)
            return redirect('/login')
        except:
            return make_response({'Error' : 'Server Error'}, 501)

    else:
        return render_template('signup.html')




# Routes
@app.route('/')
@login_required
def home():
    return render_template('index.html')


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    if request.method == 'POST':
        response = make_response()
        response.delete_cookie('access_token')
        return response

    mongo_db.posts.delete_one({'_id' : ObjectId(pid)})
    return redirect(f'/user/{uid}/posts')


if __name__ == '__main__':
    app.run(debug=True, port=5001)

