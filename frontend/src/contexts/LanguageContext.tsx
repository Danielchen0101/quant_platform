import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

// 导入语言包
import enUS from '../locales/en-US';
import zhCN from '../locales/zh-CN';

// 支持的语言类型
export type Language = 'en-US' | 'zh-CN';

// 语言包类型
export type Translation = typeof enUS;

// 上下文类型
interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: Translation;
}

// 创建上下文
const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

// 语言包映射
const translations: Record<Language, Translation> = {
  'en-US': enUS,
  'zh-CN': zhCN,
};

// 从 localStorage 获取保存的语言设置
const getStoredLanguage = (): Language => {
  const stored = localStorage.getItem('quant-platform-language');
  if (stored === 'zh-CN' || stored === 'en-US') {
    return stored;
  }
  
  // 根据浏览器语言自动选择
  const browserLang = navigator.language;
  if (browserLang.startsWith('zh')) {
    return 'zh-CN';
  }
  return 'en-US';
};

// 提供者组件
interface LanguageProviderProps {
  children: ReactNode;
}

export const LanguageProvider: React.FC<LanguageProviderProps> = ({ children }) => {
  const [language, setLanguageState] = useState<Language>(getStoredLanguage);
  const [t, setT] = useState<Translation>(translations[language]);

  // 更新语言
  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    localStorage.setItem('quant-platform-language', lang);
  };

  // 当语言改变时更新翻译
  useEffect(() => {
    setT(translations[language]);
  }, [language]);

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
};

// 自定义钩子
export const useLanguage = (): LanguageContextType => {
  const context = useContext(LanguageContext);
  if (context === undefined) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
};

// 工具函数：格式化带参数的文本
export const formatText = (text: string, params: Record<string, any> = {}): string => {
  return Object.keys(params).reduce((result, key) => {
    return result.replace(new RegExp(`\\{${key}\\}`, 'g'), String(params[key]));
  }, text);
};