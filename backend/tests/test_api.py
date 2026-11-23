from fastapi.testclient import TestClient
from app import app

def test_demo_login_and_project_lifecycle():
    with TestClient(app) as client:
        assert client.post('/api/auth/login', json={'username':'demo','password':'12345678'}).status_code == 200
        payload={'name':'API Test Project','project_type':'Office','plot_width':20,'plot_height':15,'rooms':[{'name':'Office','required_area':20,'min_width':4,'min_height':4}]}
        response=client.post('/api/projects',json=payload)
        assert response.status_code in (201,409)
        assert client.get('/api/projects').status_code == 200
