import React from 'react';
import { Target, Brain, PenTool, Network, AlertCircle } from 'lucide-react';

interface HelpModalProps {
  visible: boolean;
  onClose: () => void;
}

export const HelpModal: React.FC<HelpModalProps> = ({
  visible,
  onClose,
}) => {
  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative bg-slate-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-slate-800/50">
          <h2 className="text-2xl font-bold text-white flex items-center gap-2">
            <svg className="w-6 h-6 text-sky-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            配置帮助
          </h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-white/10 text-slate-400 transition-all"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
          <div className="max-w-3xl mx-auto space-y-8">
            {/* 配置预设说明 */}
            <section>
              <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                <Target className="w-5 h-5 text-sky-400" />
                配置预设
              </h3>
              <div className="space-y-4">
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-sky-400 mb-2">默认配置</h4>
                  <p className="text-slate-300 text-sm">适合大多数场景的平衡配置，兼顾性能和质量。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-sky-400 mb-2">高并发模式</h4>
                  <p className="text-slate-300 text-sm">适合高并发 LLM，最大化处理速度，需要较强的 LLM 提供商支持。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-sky-400 mb-2">低延迟模式</h4>
                  <p className="text-slate-300 text-sm">优先考虑响应速度，适合小文件快速处理。</p>
                </div>
              </div>
            </section>

            {/* 性能参数详解 */}
            <section>
              <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                <Brain className="w-5 h-5 text-purple-400" />
                性能参数
              </h3>
              <div className="space-y-3">
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-purple-400 mb-1">LLM 最大并发数</h4>
                  <p className="text-slate-300 text-sm">同时发送给 LLM 的最大请求数。建议根据 LLM 提供商的限制设置，一般为 1-10。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-purple-400 mb-1">LLM 请求间隔（秒）</h4>
                  <p className="text-slate-300 text-sm">两次请求之间的最小间隔。避免触发 LLM 提供商的速率限制，一般为 0.1-1.0 秒。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-purple-400 mb-1">批量写入大小</h4>
                  <p className="text-slate-300 text-sm">每批写入 Zep 的消息数量。较大的值可以提高写入效率，但会增加内存使用。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-purple-400 mb-1">批次间延迟（秒）</h4>
                  <p className="text-slate-300 text-sm">每批写入后的等待时间。避免对 Zep 服务造成过大压力。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-purple-400 mb-1">轮询间隔（秒）</h4>
                  <p className="text-slate-300 text-sm">小说列表状态更新间隔。用于定期刷新小说处理状态。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-purple-400 mb-1">状态轮询间隔（秒）</h4>
                  <p className="text-slate-300 text-sm">单个小说状态更新间隔。用于更频繁地检查特定小说的处理进度。</p>
                </div>
              </div>
            </section>

            {/* 业务参数详解 */}
            <section>
              <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                <PenTool className="w-5 h-5 text-orange-400" />
                业务参数
              </h3>
              <div className="space-y-3">
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-orange-400 mb-1">最大文件大小（MB）</h4>
                  <p className="text-slate-300 text-sm">上传文件的最大大小限制。过大的文件可能会影响处理性能。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-orange-400 mb-1">分段最小/最大长度</h4>
                  <p className="text-slate-300 text-sm">文本分段的最小和最大字符数。合理的分段可以提高 LLM 处理效率和准确性。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-orange-400 mb-1">Zep 超时时间（秒）</h4>
                  <p className="text-slate-300 text-sm">Zep API 调用的超时时间。较大的文件处理可能需要更长的超时时间。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-orange-400 mb-1">Neo4j 超时时间（秒）</h4>
                  <p className="text-slate-300 text-sm">Neo4j 操作的超时时间。复杂查询可能需要更长的超时时间。</p>
                </div>
              </div>
            </section>

            {/* API 配置指南 */}
            <section>
              <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                <Network className="w-5 h-5 text-cyan-400" />
                API 配置指南
              </h3>
              <div className="space-y-4">
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-cyan-400 mb-2">导演模型 (剧情推演)</h4>
                  <p className="text-slate-300 text-sm mb-2">需求：高质量剧情生成、NPC对话、复杂推演</p>
                  <p className="text-slate-400 text-xs">示例：GPT-4o, Claude-3.5-Sonnet, DeepSeek-Chat</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-cyan-400 mb-2">解析模型 (意图分析)</h4>
                  <p className="text-slate-300 text-sm mb-2">需求：极速解构玩家输入，追求低延迟</p>
                  <p className="text-slate-400 text-xs">示例：GPT-4o-mini, DeepSeek-Chat</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-cyan-400 mb-2">Zep 提取模型 (知识图谱)</h4>
                  <p className="text-slate-300 text-sm mb-2">需求：高质量事实提取和摘要生成</p>
                  <p className="text-slate-400 text-xs">示例：GPT-4o, GPT-4o-mini</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-cyan-400 mb-2">Graphiti 模型 (实体提取)</h4>
                  <p className="text-slate-300 text-sm mb-2">需求：高精度实体和关系提取</p>
                  <p className="text-slate-400 text-xs">示例：GPT-4o, Claude-3.5-Sonnet, DeepSeek-Chat</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-cyan-400 mb-2">Embedding 模型</h4>
                  <p className="text-slate-300 text-sm mb-2">需求：高质量文本向量化，支持语义搜索</p>
                  <p className="text-slate-400 text-xs">示例：text-embedding-v4, text-embedding-3-small, text-embedding-ada-002</p>
                </div>
              </div>
            </section>

            {/* 常见问题 */}
            <section>
              <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                <AlertCircle className="w-5 h-5 text-amber-400" />
                常见问题
              </h3>
              <div className="space-y-3">
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-amber-400 mb-1">配置修改后需要重启服务吗？</h4>
                  <p className="text-slate-300 text-sm">是的，Docker 服务需要重启才能完全生效。请点击"重启服务"按钮。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-amber-400 mb-1">如何选择合适的并发数？</h4>
                  <p className="text-slate-300 text-sm">根据 LLM 提供商的限制和网络状况调整。建议从 1 开始逐步增加，观察性能变化。</p>
                </div>
                <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                  <h4 className="font-semibold text-amber-400 mb-1">为什么需要配置多个模型？</h4>
                  <p className="text-slate-300 text-sm">不同功能对模型的需求不同。剧情推演需要高质量模型，意图解析可以使用更快的模型，这样可以优化性能和成本。</p>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
};
