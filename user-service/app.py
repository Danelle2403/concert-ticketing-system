from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Important — allows your UI to call this service

@app.route('/users', methods=['GET'])
def get_all_users():
    # return all users
    return jsonify({"users": []})

@app.route('/user/<userId>', methods=['GET'])
def get_user(userId):
    return jsonify({"userId": userId})

@app.route('/user/new', methods=['POST'])
def create_user():
    data = request.get_json()
    return jsonify({"message": "User created", "data": data}), 201

@app.route('/user/events', methods=['GET'])
def get_user_events():
    return jsonify({"events": []})

@app.route('/user/managing', methods=['GET'])
def get_managing_events():
    return jsonify({"managing": []})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

### `requirements.txt`
```
flask
flask-cors
