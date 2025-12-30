import http.server
import socketserver
import os
import cgi
import json
from urllib.parse import urlparse, unquote
import argparse

class Handler(http.server.SimpleHTTPRequestHandler):
    # 支持CORS
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    # 处理OPTIONS请求
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()
    
    # 处理GET请求，支持跨目录访问
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = unquote(parsed_path.path)
        
        # 根路径请求默认返回index.html
        if path == '/' or path == '' or path == '/index.html' :
            self.path = '/static/index.html'
        # 数据准备页面
        elif path == '/data_preparation' or path == '/data_preparation.html' :
            self.path = '/static/data_preparation.html'
        # 可视化页面
        elif path == '/visualization':
            self.path = '/static/visualization.html'
        # 模型分析页面
        elif path == '/model_analysis':
            self.path = '/static/model_analysis.html'
            
        return super().do_GET()
    
    # 处理文件上传
    def do_POST(self):
        if self.path == '/upload':
            self.handle_file_upload()
        elif self.path == '/save_config':
            self.handle_config_save()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not found')
    
    # 处理文件上传
    def handle_file_upload(self):
        try:
            # 解析multipart/form-data
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={'REQUEST_METHOD': 'POST',
                         'CONTENT_TYPE': self.headers['Content-Type'],
                        }
            )
            
            # 获取上传的文件
            file_item = form['file']
            
            if file_item.filename:
                # 创建uploads目录（如果不存在）
                upload_dir = 'uploads'
                if not os.path.exists(upload_dir):
                    os.makedirs(upload_dir)
                
                # 保存文件
                file_path = os.path.join(upload_dir, os.path.basename(file_item.filename))
                with open(file_path, 'wb') as f:
                    f.write(file_item.file.read())
                
                # 返回成功响应
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = {
                    'success': True,
                    'message': '文件上传成功',
                    'file_path': file_path,
                    'file_name': os.path.basename(file_item.filename)
                }
                self.wfile.write(json.dumps(response).encode('utf-8'))
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write('没有选择文件')
                
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f'上传失败: {str(e)}'.encode('utf-8'))
    
    # 处理配置保存
    def handle_config_save(self):
        try:
            # 读取请求内容
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            config_data = json.loads(post_data.decode('utf-8'))
            
            # 创建configs目录（如果不存在）
            config_dir = 'configs'
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
            
            # 保存配置到JSON文件
            file_name = config_data.get('phase_name', 'default_config') + '.json'
            file_path = os.path.join(config_dir, file_name)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            
            # 返回成功响应
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                'success': True,
                'message': '配置保存成功',
                'file_path': file_path
            }
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f'保存失败: {str(e)}'.encode('utf-8'))

def run_server(port=8000, root_dir='.'):
    """运行本地服务器"""
    # 更改工作目录
    os.chdir(root_dir)
    
    # 设置服务器
    handler = Handler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"本地服务器已启动，访问地址: http://localhost:{port}")
        print(f"服务根目录: {os.path.abspath(root_dir)}")
        print("按Ctrl+C停止服务器")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务器正在停止...")
            httpd.shutdown()
            print("服务器已停止")

if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='本地AL控制面板服务器')
    parser.add_argument('--port', type=int, default=8000, help='服务器端口，默认8000')
    parser.add_argument('--dir', type=str, default='.', help='服务器根目录，默认当前目录')
    args = parser.parse_args()
    
    # 运行服务器
    run_server(args.port, args.dir)
    