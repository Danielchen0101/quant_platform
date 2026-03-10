import { notification } from 'antd';

// 全局错误管理器 - 确保相同错误只显示一次
class ErrorManager {
  private static instance: ErrorManager;
  private errorCache = new Map<string, number>();
  private readonly ERROR_TTL = 5000; // 5秒
  private activeNotifications = new Set<string>();
  
  static getInstance(): ErrorManager {
    if (!ErrorManager.instance) {
      ErrorManager.instance = new ErrorManager();
    }
    return ErrorManager.instance;
  }
  
  // 生成错误唯一标识
  private getErrorKey(error: any): string {
    const url = error?.config?.url || 'unknown';
    const method = error?.config?.method || 'unknown';
    const status = error?.response?.status || 0;
    const message = error?.message || 'unknown';
    
    return `${method}:${url}:${status}:${message}`;
  }
  
  // 检查是否为重复错误
  private isDuplicateError(errorKey: string): boolean {
    const now = Date.now();
    const lastTime = this.errorCache.get(errorKey);
    
    if (lastTime && now - lastTime < this.ERROR_TTL) {
      return true;
    }
    
    this.errorCache.set(errorKey, now);
    return false;
  }
  
  // 显示错误（带去重）
  showError(error: any, customMessage?: string): boolean {
    const errorKey = this.getErrorKey(error);
    
    // 检查重复
    if (this.isDuplicateError(errorKey)) {
      console.log('[ErrorManager] 跳过重复错误:', errorKey);
      return false;
    }
    
    // 检查是否已有相同通知
    if (this.activeNotifications.has(errorKey)) {
      console.log('[ErrorManager] 已有相同通知:', errorKey);
      return false;
    }
    
    // 准备错误信息
    const errorMessage = customMessage || this.getErrorMessage(error);
    const description = this.getErrorDescription(error);
    
    // 显示通知
    notification.error({
      message: errorMessage,
      description: description,
      duration: 4.5,
      key: errorKey,
      onClose: () => {
        this.activeNotifications.delete(errorKey);
      }
    });
    
    this.activeNotifications.add(errorKey);
    return true;
  }
  
  // 获取错误消息
  private getErrorMessage(error: any): string {
    const url = error?.config?.url || '未知接口';
    const method = error?.config?.method?.toUpperCase() || '未知方法';
    
    if (error.response?.status === 404) {
      return `${method} ${url} - 接口不存在`;
    } else if (error.code === 'ECONNABORTED') {
      return `${method} ${url} - 请求超时`;
    } else if (error.code === 'NETWORK_ERROR') {
      return '网络连接失败';
    } else {
      return '网络请求失败';
    }
  }
  
  // 获取错误描述
  private getErrorDescription(error: any): string {
    const url = error?.config?.url || '未知接口';
    const method = error?.config?.method?.toUpperCase() || '未知方法';
    const status = error?.response?.status;
    const statusText = error?.response?.statusText || '未知状态';
    
    if (status) {
      return `${method} ${url}\n状态: ${status} ${statusText}`;
    } else if (error.message) {
      return `${method} ${url}\n错误: ${error.message}`;
    } else {
      return `${method} ${url}`;
    }
  }
  
  // 清除所有错误
  clearAll(): void {
    this.errorCache.clear();
    this.activeNotifications.clear();
  }
  
  // 清除旧错误
  cleanup(): void {
    const now = Date.now();
    // Fix: Use Array.from for compatibility
    Array.from(this.errorCache.entries()).forEach(([key, timestamp]) => {
      if (now - timestamp > this.ERROR_TTL * 2) {
        this.errorCache.delete(key);
      }
    });
  }
}

// 单例实例
export const errorManager = ErrorManager.getInstance();

// 定时清理
setInterval(() => {
  errorManager.cleanup();
}, 30000);

// 导出便捷函数
export function showError(error: any, customMessage?: string): boolean {
  return errorManager.showError(error, customMessage);
}

export function clearErrors(): void {
  errorManager.clearAll();
}