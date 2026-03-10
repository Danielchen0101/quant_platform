#!/usr/bin/env python3
"""
量化平台后端主入口
根据环境选择启动简化版或完整版后端
"""

import os
import sys
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """主函数"""
    logger.info("🚀 量化交易平台后端")
    logger.info("=" * 50)
    
    # 检查运行模式
    mode = os.getenv('QUANT_MODE', 'simple').lower()
    
    if mode == 'full':
        logger.info("模式: 完整版 (包含数据库和Qlib)")
        logger.info("启动 quant_backend.py...")
        
        try:
            # 导入完整版后端
            from quant_backend import app
            port = int(os.getenv('PORT', 8889))
            host = os.getenv('HOST', '0.0.0.0')
            
            logger.info(f"服务地址: http://{host}:{port}")
            logger.info("功能: 完整量化分析 + 数据库 + 用户管理")
            
            app.run(host=host, port=port, debug=True)
            
        except ImportError as e:
            logger.error(f"无法导入完整版后端: {e}")
            logger.info("请安装依赖: pip install -r requirements.txt")
            sys.exit(1)
            
    elif mode == 'simple':
        logger.info("模式: 简化版 (快速启动)")
        logger.info("启动 start_quant_backend.py...")
        
        # 运行简化版 - 直接导入并运行Flask应用
        from start_quant_backend import app
        port = int(os.getenv('PORT', 8889))
        host = os.getenv('HOST', '0.0.0.0')
        
        logger.info(f"服务地址: http://{host}:{port}")
        logger.info("功能: 简化量化分析 + Yahoo Finance数据")
        
        app.run(host=host, port=port, debug=True)
        
    else:
        logger.error(f"未知模式: {mode}")
        logger.info("可用模式: simple (简化版), full (完整版)")
        logger.info("设置环境变量: QUANT_MODE=simple 或 QUANT_MODE=full")
        sys.exit(1)

if __name__ == '__main__':
    main()