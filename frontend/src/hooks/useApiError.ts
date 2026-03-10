import { useState, useCallback, useEffect, useRef } from 'react';
import { ErrorHandler } from '../services/request-fixed';

interface UseApiErrorOptions {
  deduplicateTimeout?: number; // milliseconds
  showGlobalError?: boolean;
  context?: string;
}

interface ApiErrorState {
  hasError: boolean;
  error: any | null;
  errorCount: number;
  lastErrorTime: number | null;
}

export function useApiError(options: UseApiErrorOptions = {}) {
  const {
    deduplicateTimeout = 5000,
    showGlobalError = true,
    context = 'Component',
  } = options;
  
  const [errorState, setErrorState] = useState<ApiErrorState>({
    hasError: false,
    error: null,
    errorCount: 0,
    lastErrorTime: null,
  });
  
  const errorHandler = ErrorHandler.getInstance();
  const errorCache = useRef<Map<string, number>>(new Map());
  
  // Clear old errors from cache
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      // Fix: Use Array.from for compatibility
      Array.from(errorCache.current.entries()).forEach(([key, timestamp]) => {
        if (now - timestamp > deduplicateTimeout) {
          errorCache.current.delete(key);
        }
      });
    }, 1000);
    
    return () => clearInterval(interval);
  }, [deduplicateTimeout]);
  
  // Generate error key for deduplication
  const getErrorKey = useCallback((error: any): string => {
    const url = error?.config?.url || 'unknown';
    const method = error?.config?.method || 'unknown';
    const status = error?.response?.status || 0;
    const message = error?.message || 'unknown';
    
    return `${context}:${method}:${url}:${status}:${message}`;
  }, [context]);
  
  // Handle API error with deduplication
  const handleError = useCallback((error: any, customContext?: string) => {
    const errorContext = customContext || context;
    const errorKey = getErrorKey(error);
    const now = Date.now();
    
    // Check for duplicate error
    const lastErrorTime = errorCache.current.get(errorKey);
    if (lastErrorTime && now - lastErrorTime < deduplicateTimeout) {
      console.log(`[useApiError] Skipping duplicate error: ${errorKey}`);
      return false;
    }
    
    // Update cache
    errorCache.current.set(errorKey, now);
    
    // Update state
    setErrorState(prev => ({
      hasError: true,
      error,
      errorCount: prev.errorCount + 1,
      lastErrorTime: now,
    }));
    
    // Show global error if enabled
    if (showGlobalError) {
      errorHandler.handleApiError(error, errorContext);
    }
    
    return true;
  }, [context, deduplicateTimeout, errorHandler, getErrorKey, showGlobalError]);
  
  // Clear error state
  const clearError = useCallback(() => {
    setErrorState({
      hasError: false,
      error: null,
      errorCount: 0,
      lastErrorTime: null,
    });
  }, []);
  
  // Reset error cache
  const resetErrorCache = useCallback(() => {
    errorCache.current.clear();
  }, []);
  
  // Safe API call wrapper
  const safeApiCall = useCallback(async <T>(
    apiCall: () => Promise<T>,
    customContext?: string
  ): Promise<T | null> => {
    try {
      const result = await apiCall();
      clearError();
      return result;
    } catch (error: any) {
      handleError(error, customContext);
      return null;
    }
  }, [handleError, clearError]);
  
  // Batch API calls with single error handling
  const safeBatchApiCall = useCallback(async <T>(
    apiCalls: Array<() => Promise<T>>,
    customContext?: string
  ): Promise<Array<T | null>> => {
    try {
      const results = await Promise.allSettled(apiCalls.map(fn => fn()));
      
      const hasErrors = results.some(result => result.status === 'rejected');
      
      if (hasErrors) {
        const firstError = results.find(result => result.status === 'rejected');
        if (firstError && firstError.status === 'rejected') {
          handleError(firstError.reason, customContext);
        }
      } else {
        clearError();
      }
      
      return results.map(result => 
        result.status === 'fulfilled' ? result.value : null
      );
    } catch (error: any) {
      handleError(error, customContext);
      return apiCalls.map(() => null);
    }
  }, [handleError, clearError]);
  
  return {
    ...errorState,
    handleError,
    clearError,
    resetErrorCache,
    safeApiCall,
    safeBatchApiCall,
    
    // Helper methods
    isDuplicateError: useCallback((error: any): boolean => {
      const errorKey = getErrorKey(error);
      const lastErrorTime = errorCache.current.get(errorKey);
      return !!lastErrorTime && Date.now() - lastErrorTime < deduplicateTimeout;
    }, [getErrorKey, deduplicateTimeout]),
    
    // Error information
    getErrorDetails: useCallback((error: any) => {
      return {
        url: error?.config?.url || 'unknown',
        method: error?.config?.method || 'unknown',
        status: error?.response?.status || 0,
        statusText: error?.response?.statusText || 'unknown',
        message: error?.message || 'unknown',
        timestamp: Date.now(),
        context,
      };
    }, [context]),
  };
}

// Hook for dashboard-specific error handling
export function useDashboardError() {
  const {
    handleError,
    clearError,
    safeApiCall,
    safeBatchApiCall,
    ...errorState
  } = useApiError({
    context: 'Dashboard',
    showGlobalError: true,
  });
  
  // Dashboard-specific error handling
  const handleDashboardError = useCallback((error: any, component?: string) => {
    const context = component ? `Dashboard/${component}` : 'Dashboard';
    return handleError(error, context);
  }, [handleError]);
  
  return {
    ...errorState,
    handleDashboardError,
    clearError,
    safeApiCall,
    safeBatchApiCall,
  };
}

// Hook for initialization errors
export function useInitializationError() {
  const [initializationErrors, setInitializationErrors] = useState<Array<{
    component: string;
    error: any;
    timestamp: number;
  }>>([]);
  
  const { handleError } = useApiError({
    context: 'Initialization',
    showGlobalError: false, // We'll handle global errors manually
  });
  
  const addInitializationError = useCallback((component: string, error: any) => {
    const errorEntry = {
      component,
      error,
      timestamp: Date.now(),
    };
    
    setInitializationErrors(prev => [...prev, errorEntry]);
    
    // Only show global error if this is the first initialization error
    if (initializationErrors.length === 0) {
      handleError(error, `Initialization/${component}`);
    }
    
    return errorEntry;
  }, [handleError, initializationErrors.length]);
  
  const clearInitializationErrors = useCallback(() => {
    setInitializationErrors([]);
  }, []);
  
  const hasInitializationErrors = initializationErrors.length > 0;
  
  // Get combined error message for initialization
  const getInitializationErrorMessage = useCallback(() => {
    if (!hasInitializationErrors) return null;
    
    const errorComponents = initializationErrors.map(e => e.component).join(', ');
    return `Failed to initialize: ${errorComponents}`;
  }, [initializationErrors, hasInitializationErrors]);
  
  return {
    initializationErrors,
    hasInitializationErrors,
    addInitializationError,
    clearInitializationErrors,
    getInitializationErrorMessage,
  };
}