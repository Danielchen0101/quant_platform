#!/usr/bin/env python3
"""
网络错误诊断脚本
检查平台前后端网络连接问题
"""

import requests
import socket
import subprocess
import time
import sys
import os

def print_header(text):
    print("\n" + "="*60)
    print(f"🔍 {text}")
    print("="*60)

def print_success(text):
    print(f"✅ {text}")

def print_warning(text):
    print(f"⚠️  {text}")

def print_error(text):
    print(f"❌ {text}")

def check_port(port, service_name):
    """检查端口是否被占用"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            print_success(f"{service_name} 端口 {port} 正在监听")
            return True
        else:
            print_error(f"{service_name} 端口 {port} 未监听")
            return False
    except Exception as e:
        print_error(f"检查端口 {port} 失败: {e}")
        return False

def check_http_service(url, service_name):
    """检查HTTP服务是否响应"""
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            print_success(f"{service_name} 服务正常 (HTTP {response.status_code})")
            return True
        else:
            print_warning(f"{service_name} 服务异常 (HTTP {response.status_code})")
            return False
    except requests.exceptions.ConnectionError:
        print_error(f"{service_name} 连接失败: 服务未启动或网络问题")
        return False
    except requests.exceptions.Timeout:
        print_error(f"{service_name} 连接超时")
        return False
    except Exception as e:
        print_error(f"{service_name} 检查失败: {e}")
        return False

def check_api_endpoints():
    """检查后端API端点"""
    print_header("检查后端API端点")
    
    endpoints = [
        ("系统状态", "http://localhost:8889/api/system/status"),
        ("用户登录", "http://localhost:8889/api/auth/login"),
        ("市场数据", "http://localhost:8889/api/market/stocks"),
        ("Qlib状态", "http://localhost:8889/api/qlib/status"),
    ]
    
    results = {}
    for name, url in endpoints:
        try:
            if url.endswith("/login"):
                response = requests.post(url, json={"username": "admin", "password": "admin123"}, timeout=5)
            else:
                response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                print_success(f"{name}: HTTP {response.status_code}")
                results[name] = True
            else:
                print_warning(f"{name}: HTTP {response.status_code}")
                results[name] = False
                
        except Exception as e:
            print_error(f"{name}: {e}")
            results[name] = False
    
    return results

def check_frontend_connectivity():
    """检查前端连接性"""
    print_header("检查前端连接性")
    
    # 检查前端服务
    frontend_ok = check_http_service("http://localhost:3000", "前端React应用")
    
    # 检查前端API代理配置
    print("\n📡 前端API代理配置检查:")
    try:
        # 检查前端package.json中的proxy配置
        frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
        package_json_path = os.path.join(frontend_dir, "package.json")
        
        if os.path.exists(package_json_path):
            import json
            with open(package_json_path, 'r', encoding='utf-8') as f:
                package_data = json.load(f)
            
            proxy = package_data.get('proxy', '')
            if proxy:
                print_success(f"前端代理配置: {proxy}")
            else:
                print_warning("前端未配置代理，可能导致跨域问题")
        else:
            print_error("未找到前端package.json文件")
            
    except Exception as e:
        print_warning(f"检查代理配置失败: {e}")
    
    return frontend_ok

def check_cors_issues():
    """检查CORS跨域问题"""
    print_header("检查CORS跨域配置")
    
    try:
        # 测试OPTIONS请求（CORS预检）
        response = requests.options(
            "http://localhost:8889/api/system/status",
            headers={
                'Origin': 'http://localhost:3000',
                'Access-Control-Request-Method': 'GET',
                'Access-Control-Request-Headers': 'Content-Type,Authorization'
            },
            timeout=5
        )
        
        cors_headers = {
            'Access-Control-Allow-Origin': response.headers.get('Access-Control-Allow-Origin'),
            'Access-Control-Allow-Methods': response.headers.get('Access-Control-Allow-Methods'),
            'Access-Control-Allow-Headers': response.headers.get('Access-Control-Allow-Headers'),
        }
        
        print("CORS响应头:")
        for header, value in cors_headers.items():
            if value:
                print_success(f"  {header}: {value}")
            else:
                print_warning(f"  {header}: 未设置")
        
        if cors_headers['Access-Control-Allow-Origin'] in ['http://localhost:3000', '*']:
            print_success("CORS配置正确")
            return True
        else:
            print_warning("CORS配置可能有问题")
            return False
            
    except Exception as e:
        print_error(f"CORS检查失败: {e}")
        return False

def check_firewall_and_network():
    """检查防火墙和网络设置"""
    print_header("检查防火墙和网络设置")
    
    print("🔧 Windows防火墙检查:")
    try:
        # 检查防火墙规则
        result = subprocess.run(
            ['netsh', 'advfirewall', 'firewall', 'show', 'rule', 'name=all'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if "8889" in result.stdout or "3000" in result.stdout:
            print_success("找到相关防火墙规则")
        else:
            print_warning("未找到特定端口防火墙规则")
            
    except Exception as e:
        print_warning(f"防火墙检查失败: {e}")
    
    print("\n🌐 网络连接测试:")
    try:
        # 测试本地回环
        socket.create_connection(('127.0.0.1', 8889), timeout=5)
        print_success("本地回环连接正常")
    except Exception as e:
        print_error(f"本地回环连接失败: {e}")

def check_process_status():
    """检查进程状态"""
    print_header("检查进程状态")
    
    processes = [
        ("后端Python", "python.*app.py"),
        ("前端Node.js", "node.*react-scripts"),
    ]
    
    for name, pattern in processes:
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ['tasklist', '/FI', f'IMAGENAME eq python.exe'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if "python" in result.stdout.lower():
                    print_success(f"{name} 进程运行中")
                else:
                    print_error(f"{name} 进程未运行")
            else:
                result = subprocess.run(
                    ['pgrep', '-f', pattern],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    print_success(f"{name} 进程运行中 (PID: {result.stdout.strip()})")
                else:
                    print_error(f"{name} 进程未运行")
                    
        except Exception as e:
            print_warning(f"检查{name}进程失败: {e}")

def check_browser_console_errors():
    """模拟浏览器API调用检查"""
    print_header("模拟浏览器API调用测试")
    
    test_cases = [
        {
            "name": "直接API调用",
            "url": "http://localhost:8889/api/system/status",
            "method": "GET",
            "headers": {}
        },
        {
            "name": "带Origin头的API调用",
            "url": "http://localhost:8889/api/system/status",
            "method": "GET",
            "headers": {"Origin": "http://localhost:3000"}
        },
        {
            "name": "登录API调用",
            "url": "http://localhost:8889/api/auth/login",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "data": {"username": "admin", "password": "admin123"}
        }
    ]
    
    for test in test_cases:
        try:
            if test["method"] == "GET":
                response = requests.get(test["url"], headers=test.get("headers", {}), timeout=5)
            else:
                response = requests.post(
                    test["url"],
                    headers=test.get("headers", {}),
                    json=test.get("data", {}),
                    timeout=5
                )
            
            print_success(f"{test['name']}: HTTP {response.status_code}")
            if response.status_code != 200:
                print_warning(f"  响应内容: {response.text[:100]}")
                
        except Exception as e:
            print_error(f"{test['name']}: {e}")

def main():
    print("🔧 量化平台网络错误诊断")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"平台目录: {os.path.dirname(__file__)}")
    
    # 收集所有检查结果
    results = {}
    
    # 1. 检查端口
    print_header("1. 端口检查")
    results['backend_port'] = check_port(8889, "后端API")
    results['frontend_port'] = check_port(3000, "前端开发服务器")
    
    # 2. 检查HTTP服务
    print_header("2. HTTP服务检查")
    results['backend_service'] = check_http_service("http://localhost:8889/api/system/status", "后端API服务")
    results['frontend_service'] = check_http_service("http://localhost:3000", "前端React应用")
    
    # 3. 检查进程状态
    check_process_status()
    
    # 4. 检查API端点
    api_results = check_api_endpoints()
    results['api_endpoints'] = all(api_results.values())
    
    # 5. 检查前端连接性
    results['frontend_connectivity'] = check_frontend_connectivity()
    
    # 6. 检查CORS问题
    results['cors_config'] = check_cors_issues()
    
    # 7. 检查防火墙和网络
    check_firewall_and_network()
    
    # 8. 模拟浏览器测试
    check_browser_console_errors()
    
    # 生成诊断报告
    print_header("📋 诊断结果汇总")
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    print(f"✅ 通过: {passed}/{total}")
    print(f"❌ 失败: {total - passed}/{total}")
    
    for name, result in results.items():
        status = "✅" if result else "❌"
        print(f"  {status} {name.replace('_', ' ').title()}")
    
    print_header("🔧 问题解决方案")
    
    if not results['backend_port']:
        print("1. 启动后端服务:")
        print("   cd backend && python app.py")
        
    if not results['frontend_port']:
        print("2. 启动前端服务:")
        print("   cd frontend && npm start")
        
    if not results['cors_config']:
        print("3. 修复CORS配置:")
        print("   在后端app.py中添加:")
        print("   from flask_cors import CORS")
        print("   CORS(app, origins=['http://localhost:3000'])")
        
    if results['backend_service'] and results['frontend_service'] and not results['api_endpoints']:
        print("4. API端点问题:")
        print("   检查后端路由定义")
        print("   验证数据库连接")
        
    print_header("🚀 快速修复命令")
    print("如果服务未运行，执行以下命令:")
    print("\n启动后端:")
    print("cd ~/.openclaw/workspace/professional_quant_platform/backend")
    print("python app.py")
    
    print("\n启动前端:")
    print("cd ~/.openclaw/workspace/professional_quant_platform/frontend")
    print("npm start")
    
    print("\n验证修复:")
    print("curl http://localhost:8889/api/system/status")
    print("curl http://localhost:3000")
    
    print_header("💡 浏览器调试建议")
    print("1. 按F12打开开发者工具")
    print("2. 查看Console标签页的错误信息")
    print("3. 查看Network标签页的请求详情")
    print("4. 检查是否有CORS错误或404错误")
    
    return all(results.values())

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n诊断被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 诊断过程中发生错误: {e}")
        sys.exit(1)