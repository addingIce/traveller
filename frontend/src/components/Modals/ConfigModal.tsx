import React, { useState, useEffect, useRef } from 'react';
import {
  Settings,
  Loader2,
  RefreshCw,
  RotateCcw,
  CheckCircle,
  Save,
  Target,
  Brain,
  PenTool,
  Network,
  Info,
  AlertCircle,
} from 'lucide-react';
import { SystemConfig, testLLMConnectivity, LLMConnectivityTestRequest } from '../../api';

interface ConfigModalProps {
  visible: boolean;
  config: SystemConfig | null;
  isConfigLoading: boolean;
  configSaveStatus: 'idle' | 'saving' | 'saved' | 'error';
  isRestarting: boolean;
  onClose: () => void;
  onSave: (config: SystemConfig) => Promise<void>;
  onReset: () => Promise<void>;
  onRestart: () => Promise<void>;
  onShowHelp: () => void;
}

type ConnectivityStatus = 'idle' | 'testing' | 'success' | 'error';

interface ConnectivityUIResult {
  status: ConnectivityStatus;
  message: string;
}

export const ConfigModal: React.FC<ConfigModalProps> = ({
  visible,
  config: initialConfig,
  isConfigLoading,
  configSaveStatus,
  isRestarting,
  onClose,
  onSave,
  onReset,
  onRestart,
  onShowHelp,
}) => {
  const [config, setConfig] = useState<SystemConfig | null>(initialConfig);
  const [selectedPreset, setSelectedPreset] = useState<string>('');
  const [activeSection, setActiveSection] = useState<string>('presets');
  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<{ llm: ConnectivityUIResult; embedding: ConnectivityUIResult }>({
    llm: { status: 'idle', message: '' },
    embedding: { status: 'idle', message: '' },
  });
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setConfig(initialConfig);
    setTestResult({
      llm: { status: 'idle', message: '' },
      embedding: { status: 'idle', message: '' },
    });
  }, [initialConfig]);

  const resetTestResult = (target: 'llm' | 'embedding') => {
    setTestResult((prev) => ({
      ...prev,
      [target]: { status: 'idle', message: '' },
    }));
  };

  const handleTestConnectivity = async () => {
    if (!config || isTesting) return;
    const payload: LLMConnectivityTestRequest = {
      llm_api_key: config.api.llm_api_key,
      llm_base_url: config.api.llm_base_url,
      llm_model: config.api.model_director,
      embedding_api_key: config.api.embedding_api_key,
      embedding_base_url: config.api.embedding_base_url,
      embedding_model: config.api.embedding_model,
    };

    setIsTesting(true);
    setTestResult({
      llm: { status: 'testing', message: '测试中...' },
      embedding: { status: 'testing', message: '测试中...' },
    });

    try {
      const result = await testLLMConnectivity(payload);
      setTestResult({
        llm: {
          status: result.llm.ok ? 'success' : 'error',
          message: result.llm.message || (result.llm.ok ? 'LLM 可用' : 'LLM 不可用'),
        },
        embedding: {
          status: result.embedding.ok ? 'success' : 'error',
          message: result.embedding.message || (result.embedding.ok ? 'Embedding 可用' : 'Embedding 不可用'),
        },
      });
    } catch (error) {
      console.error("测试 LLM 接口失败", error);
      setTestResult({
        llm: { status: 'error', message: '测试请求失败，请检查后端服务' },
        embedding: { status: 'error', message: '测试请求失败，请检查后端服务' },
      });
    } finally {
      setIsTesting(false);
    }
  };

  const scrollToSection = (sectionId: string) => {
    setActiveSection(sectionId);
    const element = document.getElementById(sectionId);
    if (element && contentRef.current) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const handleApplyPreset = async (presetKey: string) => {
    setSelectedPreset(presetKey);
    // 预设值
    const presets: Record<string, Partial<SystemConfig>> = {
      default: {
        performance: {
          graphiti_llm_max_concurrency: 5,
          graphiti_llm_min_interval: 0.5,
          batch_size: 10,
          batch_delay: 0.5,
          poll_interval: 2,
          status_poll_interval: 1,
        },
      },
      high_concurrency: {
        performance: {
          graphiti_llm_max_concurrency: 20,
          graphiti_llm_min_interval: 0.1,
          batch_size: 20,
          batch_delay: 0.1,
          poll_interval: 1,
          status_poll_interval: 0.5,
        },
      },
      low_latency: {
        performance: {
          graphiti_llm_max_concurrency: 3,
          graphiti_llm_min_interval: 0.3,
          batch_size: 5,
          batch_delay: 0.2,
          poll_interval: 1,
          status_poll_interval: 0.5,
        },
      },
    };

    if (config && presets[presetKey]) {
      setConfig({
        ...config,
        ...presets[presetKey],
      });
    }
  };

  const handleSave = async () => {
    if (config) {
      await onSave(config);
    }
  };

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative bg-slate-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-slate-800/50">
          <div>
            <h2 className="text-2xl font-bold text-white flex items-center gap-2">
              <Settings className="w-6 h-6 text-emerald-400" />
              系统配置
            </h2>
            <p className="text-sm text-slate-400 mt-1">配置系统参数，调整后立即生效</p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={onRestart}
              disabled={isRestarting}
              className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-600 text-white text-sm transition-all flex items-center gap-2 disabled:opacity-50"
            >
              {isRestarting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  重启中...
                </>
              ) : (
                <>
                  <RefreshCw className="w-4 h-4" />
                  重启服务
                </>
              )}
            </button>
            <button
              onClick={onReset}
              className="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 text-sm transition-all flex items-center gap-2"
            >
              <RotateCcw className="w-4 h-4" />
              重置
            </button>
            <button
              onClick={handleSave}
              disabled={configSaveStatus === 'saving'}
              className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm transition-all flex items-center gap-2 disabled:opacity-50"
            >
              {configSaveStatus === 'saving' ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  保存中...
                </>
              ) : configSaveStatus === 'saved' ? (
                <>
                  <CheckCircle className="w-4 h-4" />
                  已保存
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  保存配置
                </>
              )}
            </button>
            <button
              onClick={onShowHelp}
              className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-600 text-white text-sm transition-all flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              帮助
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-white/10 text-slate-400 transition-all"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 flex overflow-hidden">
          {/* Sidebar Navigation */}
          <div className="w-48 border-r border-white/10 p-4 flex flex-col gap-2">
            <button
              onClick={() => scrollToSection('presets')}
              className={`text-left px-4 py-3 rounded-lg transition-all ${
                activeSection === 'presets'
                  ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30'
                  : 'hover:bg-white/5 text-slate-400'
              }`}
            >
              配置预设
            </button>
            <button
              onClick={() => scrollToSection('performance')}
              className={`text-left px-4 py-3 rounded-lg transition-all ${
                activeSection === 'performance'
                  ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30'
                  : 'hover:bg-white/5 text-slate-400'
              }`}
            >
              性能参数
            </button>
            <button
              onClick={() => scrollToSection('business')}
              className={`text-left px-4 py-3 rounded-lg transition-all ${
                activeSection === 'business'
                  ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30'
                  : 'hover:bg-white/5 text-slate-400'
              }`}
            >
              业务参数
            </button>
            <button
              onClick={() => scrollToSection('api')}
              className={`text-left px-4 py-3 rounded-lg transition-all ${
                activeSection === 'api'
                  ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30'
                  : 'hover:bg-white/5 text-slate-400'
              }`}
            >
              API 配置
            </button>
          </div>

          {/* Config Content */}
          <div ref={contentRef} className="flex-1 overflow-y-auto p-6 custom-scrollbar">
            {isConfigLoading ? (
              <div className="flex flex-col items-center justify-center py-20">
                <Loader2 className="w-12 h-12 mb-4 animate-spin opacity-50 text-emerald-400" />
                <p className="text-sm tracking-wider">正在加载配置...</p>
              </div>
            ) : config ? (
              <div className="max-w-4xl mx-auto space-y-6">
                {/* Presets */}
                <div id="presets" className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 scroll-mt-4">
                  <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Target className="w-5 h-5 text-sky-400" />
                    配置预设
                  </h3>
                  <div className="grid grid-cols-3 gap-4">
                    <button
                      onClick={() => handleApplyPreset('default')}
                      className={`p-4 rounded-xl border transition-all ${
                        selectedPreset === 'default'
                          ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-400'
                          : 'bg-white/5 border-white/10 hover:border-sky-500/50 text-slate-300'
                      }`}
                    >
                      <div className="font-medium">默认配置</div>
                      <div className="text-xs text-slate-500 mt-1">适合大多数场景</div>
                    </button>
                    <button
                      onClick={() => handleApplyPreset('high_concurrency')}
                      className={`p-4 rounded-xl border transition-all ${
                        selectedPreset === 'high_concurrency'
                          ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-400'
                          : 'bg-white/5 border-white/10 hover:border-sky-500/50 text-slate-300'
                      }`}
                    >
                      <div className="font-medium">高并发模式</div>
                      <div className="text-xs text-slate-500 mt-1">无限制 LLM</div>
                    </button>
                    <button
                      onClick={() => handleApplyPreset('low_latency')}
                      className={`p-4 rounded-xl border transition-all ${
                        selectedPreset === 'low_latency'
                          ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-400'
                          : 'bg-white/5 border-white/10 hover:border-sky-500/50 text-slate-300'
                      }`}
                    >
                      <div className="font-medium">低延迟模式</div>
                      <div className="text-xs text-slate-500 mt-1">快速响应</div>
                    </button>
                  </div>
                </div>

                {/* Performance Config */}
                <div id="performance" className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 scroll-mt-4">
                  <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Brain className="w-5 h-5 text-purple-400" />
                    性能参数
                  </h3>
                  <div className="grid grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">LLM 最大并发数</label>
                      <input
                        type="number"
                        value={config.performance.graphiti_llm_max_concurrency}
                        onChange={(e) => setConfig({
                          ...config,
                          performance: {
                            ...config.performance,
                            graphiti_llm_max_concurrency: parseInt(e.target.value) || 1
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">同时发送给 LLM 的最大请求数</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">LLM 请求间隔（秒）</label>
                      <input
                        type="number"
                        step="0.1"
                        value={config.performance.graphiti_llm_min_interval}
                        onChange={(e) => setConfig({
                          ...config,
                          performance: {
                            ...config.performance,
                            graphiti_llm_min_interval: parseFloat(e.target.value) || 0.1
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">两次请求之间的最小间隔</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">批量写入大小</label>
                      <input
                        type="number"
                        value={config.performance.batch_size}
                        onChange={(e) => setConfig({
                          ...config,
                          performance: {
                            ...config.performance,
                            batch_size: parseInt(e.target.value) || 1
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">每批写入 Zep 的消息数量</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">批次间延迟（秒）</label>
                      <input
                        type="number"
                        step="0.1"
                        value={config.performance.batch_delay}
                        onChange={(e) => setConfig({
                          ...config,
                          performance: {
                            ...config.performance,
                            batch_delay: parseFloat(e.target.value) || 0.1
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">每批写入后的等待时间</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">轮询间隔（秒）</label>
                      <input
                        type="number"
                        value={config.performance.poll_interval}
                        onChange={(e) => setConfig({
                          ...config,
                          performance: {
                            ...config.performance,
                            poll_interval: parseInt(e.target.value) || 1
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">小说列表状态更新间隔</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">状态轮询间隔（秒）</label>
                      <input
                        type="number"
                        value={config.performance.status_poll_interval}
                        onChange={(e) => setConfig({
                          ...config,
                          performance: {
                            ...config.performance,
                            status_poll_interval: parseInt(e.target.value) || 1
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">单个小说状态更新间隔</p>
                    </div>
                  </div>
                </div>

                {/* Business Config */}
                <div id="business" className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 scroll-mt-4">
                  <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <PenTool className="w-5 h-5 text-orange-400" />
                    业务参数
                  </h3>
                  <div className="grid grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">最大文件大小（MB）</label>
                      <input
                        type="number"
                        value={config.business.max_file_size_mb}
                        onChange={(e) => setConfig({
                          ...config,
                          business: {
                            ...config.business,
                            max_file_size_mb: parseInt(e.target.value) || 1
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">上传文件的最大大小</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">分段最小长度</label>
                      <input
                        type="number"
                        value={config.business.chunk_min_length}
                        onChange={(e) => setConfig({
                          ...config,
                          business: {
                            ...config.business,
                            chunk_min_length: parseInt(e.target.value) || 10
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">文本分段的最小字符数</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">分段最大长度</label>
                      <input
                        type="number"
                        value={config.business.chunk_max_length}
                        onChange={(e) => setConfig({
                          ...config,
                          business: {
                            ...config.business,
                            chunk_max_length: parseInt(e.target.value) || 100
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">文本分段的最大字符数</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">Zep 超时时间（秒）</label>
                      <input
                        type="number"
                        value={config.business.zep_timeout}
                        onChange={(e) => setConfig({
                          ...config,
                          business: {
                            ...config.business,
                            zep_timeout: parseInt(e.target.value) || 60
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">Zep API 调用的超时时间</p>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-slate-300">Neo4j 超时时间（秒）</label>
                      <input
                        type="number"
                        value={config.business.neo4j_timeout}
                        onChange={(e) => setConfig({
                          ...config,
                          business: {
                            ...config.business,
                            neo4j_timeout: parseInt(e.target.value) || 30
                          }
                        })}
                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                      />
                      <p className="text-xs text-slate-500">Neo4j 操作的超时时间</p>
                    </div>
                  </div>
                </div>

                {/* API Config */}
                <div id="api" className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 scroll-mt-4">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                      <Network className="w-5 h-5 text-cyan-400" />
                      API 配置
                    </h3>
                    <button
                      onClick={handleTestConnectivity}
                      disabled={isTesting}
                      className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-600 text-white text-sm transition-all flex items-center gap-2 disabled:opacity-50"
                    >
                      {isTesting ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          测试中...
                        </>
                      ) : (
                        <>
                          <Network className="w-4 h-4" />
                          测试接口
                        </>
                      )}
                    </button>
                  </div>
                  <div className="space-y-6">
                    <div className="grid grid-cols-2 gap-6">
                      <div className="space-y-2">
                        <label className="text-sm text-slate-300">LLM API Key</label>
                        <input
                          type="password"
                          value={config.api.llm_api_key}
                          onChange={(e) => {
                            setConfig({
                              ...config,
                              api: {
                                ...config.api,
                                llm_api_key: e.target.value
                              }
                            });
                            resetTestResult('llm');
                          }}
                          className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                          placeholder="sk-..."
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm text-slate-300">LLM Base URL</label>
                        <input
                          type="text"
                          value={config.api.llm_base_url}
                          onChange={(e) => {
                            setConfig({
                              ...config,
                              api: {
                                ...config.api,
                                llm_base_url: e.target.value
                              }
                            });
                            resetTestResult('llm');
                          }}
                          className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                          placeholder="https://api.openai.com/v1"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className={`rounded-xl border px-4 py-3 ${testResult.llm.status === 'success' ? 'bg-emerald-500/10 border-emerald-500/30' : testResult.llm.status === 'error' ? 'bg-red-500/10 border-red-500/30' : 'bg-white/5 border-white/10'}`}>
                        <div className="flex items-center gap-2 mb-1">
                          {testResult.llm.status === 'success' ? (
                            <CheckCircle className="w-4 h-4 text-emerald-400" />
                          ) : testResult.llm.status === 'error' ? (
                            <AlertCircle className="w-4 h-4 text-red-400" />
                          ) : testResult.llm.status === 'testing' ? (
                            <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />
                          ) : (
                            <Info className="w-4 h-4 text-slate-400" />
                          )}
                          <span className="text-sm font-medium text-white">LLM 接口</span>
                        </div>
                        <p className="text-xs text-slate-300">
                          {testResult.llm.status === 'idle' ? '未测试' : testResult.llm.message}
                        </p>
                      </div>

                      <div className={`rounded-xl border px-4 py-3 ${testResult.embedding.status === 'success' ? 'bg-emerald-500/10 border-emerald-500/30' : testResult.embedding.status === 'error' ? 'bg-red-500/10 border-red-500/30' : 'bg-white/5 border-white/10'}`}>
                        <div className="flex items-center gap-2 mb-1">
                          {testResult.embedding.status === 'success' ? (
                            <CheckCircle className="w-4 h-4 text-emerald-400" />
                          ) : testResult.embedding.status === 'error' ? (
                            <AlertCircle className="w-4 h-4 text-red-400" />
                          ) : testResult.embedding.status === 'testing' ? (
                            <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />
                          ) : (
                            <Info className="w-4 h-4 text-slate-400" />
                          )}
                          <span className="text-sm font-medium text-white">Embedding 接口</span>
                        </div>
                        <p className="text-xs text-slate-300">
                          {testResult.embedding.status === 'idle' ? '未测试' : testResult.embedding.message}
                        </p>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-6">
                      <div className="space-y-2">
                        <label className="text-sm text-slate-300">Embedding API Key</label>
                        <input
                          type="password"
                          value={config.api.embedding_api_key}
                          onChange={(e) => {
                            setConfig({
                              ...config,
                              api: {
                                ...config.api,
                                embedding_api_key: e.target.value
                              }
                            });
                            resetTestResult('embedding');
                          }}
                          className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                          placeholder="sk-..."
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm text-slate-300">Embedding Base URL</label>
                        <input
                          type="text"
                          value={config.api.embedding_base_url}
                          onChange={(e) => {
                            setConfig({
                              ...config,
                              api: {
                                ...config.api,
                                embedding_base_url: e.target.value
                              }
                            });
                            resetTestResult('embedding');
                          }}
                          className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                          placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm text-slate-300">Embedding 模型</label>
                        <input
                          type="text"
                          value={config.api.embedding_model}
                          onChange={(e) => {
                            setConfig({
                              ...config,
                              api: {
                                ...config.api,
                                embedding_model: e.target.value
                              }
                            });
                            resetTestResult('embedding');
                          }}
                          className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                          placeholder="text-embedding-v4"
                        />
                      </div>
                    </div>

                    {/* 独立模型配置 */}
                    <div className="border-t border-white/10 pt-6">
                      <h4 className="text-sm font-semibold text-cyan-400 mb-4 flex items-center gap-2">
                        <Network className="w-4 h-4" />
                        功能模型配置
                      </h4>
                      <div className="grid grid-cols-2 gap-6">
                        <div className="space-y-2">
                          <label className="text-sm text-slate-300">导演模型 (剧情推演)</label>
                          <input
                            type="text"
                            value={config.api.model_director}
                            onChange={(e) => {
                              setConfig({
                                ...config,
                                api: {
                                  ...config.api,
                                  model_director: e.target.value
                                }
                              });
                              resetTestResult('llm');
                            }}
                            className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                            placeholder="gpt-4o"
                          />
                          <p className="text-xs text-slate-500">用于剧情生成、NPC对话、复杂推演</p>
                        </div>
                        <div className="space-y-2">
                          <label className="text-sm text-slate-300">解析模型 (意图分析)</label>
                          <input
                            type="text"
                            value={config.api.model_parser}
                            onChange={(e) => setConfig({
                              ...config,
                              api: {
                                ...config.api,
                                model_parser: e.target.value
                              }
                            })}
                            className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                            placeholder="gpt-4o-mini"
                          />
                          <p className="text-xs text-slate-500">用于极速解构玩家输入，追求低延迟</p>
                        </div>
                        <div className="space-y-2">
                          <label className="text-sm text-slate-300">Zep 提取模型 (知识图谱)</label>
                          <input
                            type="text"
                            value={config.api.model_zep_extractor}
                            onChange={(e) => setConfig({
                              ...config,
                              api: {
                                ...config.api,
                                model_zep_extractor: e.target.value
                              }
                            })}
                            className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                            placeholder="gpt-4o-mini"
                          />
                          <p className="text-xs text-slate-500">用于高质量事实提取和摘要生成</p>
                        </div>
                        <div className="space-y-2">
                          <label className="text-sm text-slate-300">Graphiti 模型 (实体提取)</label>
                          <input
                            type="text"
                            value={config.api.model_graphiti}
                            onChange={(e) => setConfig({
                              ...config,
                              api: {
                                ...config.api,
                                model_graphiti: e.target.value
                              }
                            })}
                            className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                            placeholder="gpt-4o"
                          />
                          <p className="text-xs text-slate-500">用于高精度实体和关系提取</p>
                        </div>
                      </div>
                    </div>

                    <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 flex items-start gap-3">
                      <Info className="w-5 h-5 text-emerald-400 mt-0.5 flex-shrink-0" />
                      <div className="text-sm text-slate-300">
                        <p className="font-medium text-emerald-400 mb-1">配置提示</p>
                        <p>API Key 将保存到后端 .env 文件中。修改后需要重启 Docker 服务才能完全生效。</p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
};
