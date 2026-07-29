from flasgger import Swagger

from app import create_app
from app.extensions import db

app = create_app()

swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "線上點餐系統 API 文件",
        "description": "點餐系統後端 API 說明文件（Swagger UI）",
        "version": "1.0.0",
    },
    "securityDefinitions": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": '請輸入 "Bearer {access_token}"',
        }
    },
}
swagger = Swagger(app, template=swagger_template)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        print("資料表已建立/確認完成：", list(db.metadata.tables.keys()))

    app.run(debug=True)
