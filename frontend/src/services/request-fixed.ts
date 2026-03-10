import type { AxiosRequestConfig, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import axios from 'axios';
import { errorManager } from './error-manager';

// Error deduplication constants
const ERROR_CACHE_TTL = 5000; // 5 seconds

// Generate error cache key
function getErrorCacheKey(error: any): string {
  const url = error?.config?.url || 'unknown';
  const method = error?.config?.method || 'unknown';
  const status = error?.response?.status || 0;
  const message = error?.message || 'unknown';
  
  return `${method}:${url}:${status}:${message}`;
}

// Show deduplicated error message
function showDeduplicatedError(error: any, customMessage?: string) {
  return errorManager.showError(error, customMessage);
}

// Get detailed error description
function getErrorDescription(error: any): string {
  const url = error?.config?.url || 'Unknown endpoint';
  const method = error?.config?.method?.toUpperCase() || 'Unknown method';
  const status = error?.response?.status;
  const statusText = error?.response?.statusText || 'Unknown status';
  
  if (status) {
    return `${method} ${url} - ${status} ${statusText}`;
  } else if (error.code === 'ECONNABORTED') {
    return `Request timeout: ${method} ${url}`;
  } else if (error.code === 'NETWORK_ERROR') {
    return `Network error: Cannot connect to server`;
  } else {
    return `${method} ${url} - ${error.message || 'Unknown error'}`;
  }
}

// Create axios instance with improved error handling
const request = axios.create({
  baseURL: process.env.REACT_APP_API_BASE_URL || 'http://localhost:8889',
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Add timestamp to track request timing
    (config as any).requestTimestamp = Date.now();
    
    // Add request ID for tracking
    (config as any).requestId = Math.random().toString(36).substr(2, 9);
    
    return config;
  },
  (error: any) => {
    console.error('[Request Interceptor Error]', error);
    return Promise.reject(error);
  }
);

// Response interceptor with deduplicated error handling
request.interceptors.response.use(
  (response: AxiosResponse) => {
    // Calculate request duration
    const requestTimestamp = (response.config as any).requestTimestamp;
    if (requestTimestamp) {
      const duration = Date.now() - requestTimestamp;
      console.log(`[Request ${(response.config as any).requestId}] ${response.config.method?.toUpperCase()} ${response.config.url} - ${duration}ms`);
    }
    
    return response;
  },
  (error: any) => {
    const config = error.config;
    const requestId = (config as any).requestId || 'unknown';
    const url = config?.url || 'unknown';
    const method = config?.method?.toUpperCase() || 'unknown';
    
    console.error(`[Request ${requestId} Failed] ${method} ${url}`, error);
    
    // Check if this is a retry attempt
    const retryCount = (config as any).retryCount || 0;
    const maxRetries = 2;
    
    // Don't retry for certain errors
    const shouldRetry = 
      error.code === 'ECONNABORTED' || // Timeout
      error.code === 'NETWORK_ERROR' || // Network issues
      (!error.response && retryCount < maxRetries); // No response
    
    if (shouldRetry) {
      (config as any).retryCount = retryCount + 1;
      const delay = Math.min(1000 * Math.pow(2, retryCount), 5000);
      
      console.log(`[Request ${requestId}] Retrying (${retryCount + 1}/${maxRetries}) in ${delay}ms`);
      
      return new Promise(resolve => {
        setTimeout(() => resolve(request(config)), delay);
      });
    }
    
    // Show deduplicated error
    showDeduplicatedError(error);
    
    return Promise.reject(error);
  }
);

// API error types
export interface ApiError {
  code: string;
  message: string;
  details?: any;
}

// Error handler for components
export class ErrorHandler {
  private static instance: ErrorHandler;
  private activeErrors = new Set<string>();
  
  static getInstance(): ErrorHandler {
    if (!ErrorHandler.instance) {
      ErrorHandler.instance = new ErrorHandler();
    }
    return ErrorHandler.instance;
  }
  
  // Handle API error with deduplication
  handleApiError(error: any, context?: string): void {
    const errorId = `${context || 'unknown'}:${getErrorCacheKey(error)}`;
    
    // Skip if already handling this error
    if (this.activeErrors.has(errorId)) {
      console.log(`[ErrorHandler] Skipping duplicate error in context: ${context}`);
      return;
    }
    
    this.activeErrors.add(errorId);
    
    // Show error with context
    const errorMessage = context ? `${context}: Network request failed` : 'Network request failed';
    showDeduplicatedError(error, errorMessage);
    
    // Remove from active errors after TTL
    setTimeout(() => {
      this.activeErrors.delete(errorId);
    }, ERROR_CACHE_TTL);
  }
  
  // Clear all active errors
  clear(): void {
    this.activeErrors.clear();
  }
}

// Hook for component error handling
export function useErrorHandler() {
  const handler = ErrorHandler.getInstance();
  
  return {
    handleError: (error: any, context?: string) => handler.handleApiError(error, context),
    clearErrors: () => handler.clear(),
  };
}

// Request wrapper with better error handling
export async function safeRequest<T = any>(
  requestFn: () => Promise<AxiosResponse<T>>,
  context?: string
): Promise<T | null> {
  try {
    const response = await requestFn();
    return response.data;
  } catch (error: any) {
    const handler = ErrorHandler.getInstance();
    handler.handleApiError(error, context);
    return null;
  }
}

// Batch request with single error handling
export async function batchRequest<T = any>(
  requests: Array<() => Promise<AxiosResponse<T>>>,
  context?: string
): Promise<Array<T | null>> {
  try {
    const responses = await Promise.allSettled(requests.map(fn => fn()));
    
    const results: Array<T | null> = [];
    let hasErrors = false;
    
    responses.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        results.push(result.value.data);
      } else {
        results.push(null);
        hasErrors = true;
      }
    });
    
    // Show single error if any request failed
    if (hasErrors) {
      const handler = ErrorHandler.getInstance();
      handler.handleApiError(new Error('One or more requests failed'), context);
    }
    
    return results;
  } catch (error: any) {
    const handler = ErrorHandler.getInstance();
    handler.handleApiError(error, context);
    return requests.map(() => null);
  }
}

export default request;