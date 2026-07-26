'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Upload, FileText, Search, Trash2, Brain, BookOpen, 
  Loader2, CheckCircle, Plus 
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

interface Document {
  doc_hash: string;
  filename: string;
  chunk_count: number;
  ingested_at: string;
}

interface SearchResult {
  text: string;
  doc_name: string;
  score: number;
}

export default function KnowledgeHubPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [guideline, setGuideline] = useState('');
  const [guidelineStatus, setGuidelineStatus] = useState<'idle' | 'saving' | 'success' | 'error'>('idle');

  const loadDocuments = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/documents`);
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
      }
    } catch (err) {
      console.error('Failed to load documents:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDocuments();
  }, []);

  useEffect(() => {
    const timer = setTimeout(async () => {
      if (!searchQuery.trim()) {
        setSearchResults([]);
        return;
      }
      setIsSearching(true);
      try {
        const res = await fetch(`${API_BASE}/api/knowledge/search?q=${encodeURIComponent(searchQuery)}`);
        if (res.ok) {
          const data = await res.json();
          setSearchResults(data.results || []);
        }
      } catch (err) {
        console.error('Search failed:', err);
      } finally {
        setIsSearching(false);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setUploadProgress(0);
    const interval = setInterval(() => {
      setUploadProgress(p => Math.min(p + 10, 90));
    }, 200);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${API_BASE}/api/knowledge/upload`, {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        setUploadProgress(100);
        await loadDocuments();
      }
    } catch (err) {
      console.error('Upload failed:', err);
    } finally {
      clearInterval(interval);
      setTimeout(() => {
        setUploading(false);
        setUploadProgress(0);
      }, 500);
    }
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleUpload(e.dataTransfer.files[0]);
    }
  }, []);

  const handleDelete = async (docHash: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/documents/${docHash}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setDocuments(documents.filter(d => d.doc_hash !== docHash));
      }
    } catch (err) {
      console.error('Delete failed:', err);
    }
  };

  const handleAddGuideline = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!guideline.trim()) return;
    setGuidelineStatus('saving');
    try {
      const res = await fetch(`${API_BASE}/api/memory/guidelines`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ guideline }),
      });
      if (res.ok) {
        setGuidelineStatus('success');
        setGuideline('');
        setTimeout(() => setGuidelineStatus('idle'), 3000);
      } else {
        setGuidelineStatus('error');
      }
    } catch (err) {
      setGuidelineStatus('error');
    }
  };

  const totalChunks = documents.reduce((acc, doc) => acc + (doc.chunk_count || 0), 0);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 p-8 font-sans">
      <div className="max-w-[1200px] mx-auto flex flex-col gap-8">
        {/* Header */}
        <motion.div 
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col gap-2"
        >
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <Brain className="w-8 h-8 text-purple-500" />
            Knowledge Hub
          </h1>
          <p className="text-slate-400">Manage your organization's RAG knowledge base and brand guidelines.</p>
        </motion.div>

        {/* Stats Row */}
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="grid grid-cols-1 md:grid-cols-2 gap-4"
        >
          <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 rounded-2xl p-6 shadow-xl relative overflow-hidden">
            <div className="absolute top-0 right-0 p-4 opacity-10">
              <BookOpen className="w-24 h-24 text-blue-500" />
            </div>
            <div className="relative z-10">
              <p className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-2">Total Documents</p>
              <p className="text-4xl font-bold text-white">{documents.length}</p>
            </div>
          </div>
          <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 rounded-2xl p-6 shadow-xl relative overflow-hidden">
            <div className="absolute top-0 right-0 p-4 opacity-10">
              <Brain className="w-24 h-24 text-purple-500" />
            </div>
            <div className="relative z-10">
              <p className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-2">Total Chunks Indexed</p>
              <p className="text-4xl font-bold text-white">{totalChunks}</p>
            </div>
          </div>
        </motion.div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Left Column */}
          <div className="lg:col-span-1 flex flex-col gap-6">
            <motion.div 
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.2 }}
              className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 rounded-2xl p-6 shadow-xl"
            >
              <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <Upload className="w-5 h-5 text-blue-400" /> Upload Document
              </h2>
              
              <div 
                onDragOver={(e) => e.preventDefault()}
                onDrop={onDrop}
                className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-all duration-200 ${
                  uploading 
                    ? 'border-blue-500/50 bg-blue-500/5' 
                    : 'border-slate-700 hover:border-slate-500 hover:bg-slate-800/50 cursor-pointer'
                }`}
              >
                <input 
                  type="file" 
                  accept=".pdf,.docx,.txt"
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
                  onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
                  disabled={uploading}
                />
                <div className="flex flex-col items-center gap-3">
                  {uploading ? (
                    <>
                      <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
                      <div className="w-full">
                        <p className="text-sm font-medium text-white mb-2">Processing Document...</p>
                        <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                          <div 
                            className="h-full bg-blue-500 transition-all duration-300"
                            style={{ width: `${uploadProgress}%` }}
                          />
                        </div>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="w-12 h-12 bg-slate-800 rounded-full flex items-center justify-center">
                        <Upload className="w-6 h-6 text-slate-400" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-slate-300">Drag & drop or click</p>
                        <p className="text-xs text-slate-500 mt-1">Supports PDF, DOCX, TXT</p>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </motion.div>

            <motion.div 
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3 }}
              className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 rounded-2xl p-6 shadow-xl"
            >
              <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <BookOpen className="w-5 h-5 text-purple-400" /> Brand Guidelines
              </h2>
              <form onSubmit={handleAddGuideline} className="flex flex-col gap-3">
                <textarea
                  value={guideline}
                  onChange={(e) => setGuideline(e.target.value)}
                  placeholder="E.g. We always use friendly, professional tone. Never mention competitors..."
                  className="w-full bg-slate-950/50 border border-slate-700/50 rounded-xl p-4 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-purple-500/50 focus:border-purple-500/50 resize-none min-h-[120px]"
                />
                <button
                  type="submit"
                  disabled={guidelineStatus === 'saving' || !guideline.trim()}
                  className="w-full bg-purple-600 hover:bg-purple-700 disabled:bg-slate-800 disabled:text-slate-500 text-white font-medium text-sm py-2.5 rounded-xl transition-colors flex items-center justify-center gap-2"
                >
                  {guidelineStatus === 'saving' ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : guidelineStatus === 'success' ? (
                    <><CheckCircle className="w-4 h-4" /> Added successfully</>
                  ) : (
                    <><Plus className="w-4 h-4" /> Add Guideline</>
                  )}
                </button>
              </form>
            </motion.div>
          </div>

          {/* Right Column */}
          <div className="lg:col-span-2 flex flex-col gap-6">
            <motion.div 
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.2 }}
              className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 rounded-2xl p-6 shadow-xl"
            >
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <Search className="h-5 w-5 text-slate-500" />
                </div>
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Ask a question or search documents..."
                  className="block w-full bg-slate-950/50 border border-slate-700/50 rounded-xl py-3 pl-11 pr-11 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-all"
                />
                {isSearching && (
                  <div className="absolute inset-y-0 right-0 pr-4 flex items-center pointer-events-none">
                    <Loader2 className="h-4 w-4 text-slate-500 animate-spin" />
                  </div>
                )}
              </div>

              <AnimatePresence>
                {searchQuery && (
                  <motion.div 
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="mt-4 flex flex-col gap-3 overflow-hidden"
                  >
                    {searchResults.length > 0 ? (
                      searchResults.map((result, idx) => (
                        <div key={idx} className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-4 text-sm">
                          <p className="text-slate-300 italic mb-2 leading-relaxed">"{result.text}"</p>
                          <div className="flex items-center gap-2 text-xs text-slate-500 font-medium">
                            <FileText className="w-3 h-3" />
                            {result.doc_name}
                            <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 ml-auto">
                              Score: {result.score.toFixed(2)}
                            </span>
                          </div>
                        </div>
                      ))
                    ) : (
                      !isSearching && (
                        <div className="text-center py-8 text-slate-500 text-sm">
                          No matches found for "{searchQuery}"
                        </div>
                      )
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>

            <motion.div 
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3 }}
              className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 rounded-2xl shadow-xl overflow-hidden flex flex-col flex-1"
            >
              <div className="p-6 border-b border-slate-800/60 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                  <FileText className="w-5 h-5 text-blue-400" /> Document Repository
                </h2>
              </div>
              
              <div className="p-6 flex-1 min-h-[300px]">
                {loading ? (
                  <div className="flex flex-col gap-3">
                    {[1,2,3].map(i => (
                      <div key={i} className="h-16 bg-slate-800/30 animate-pulse rounded-xl" />
                    ))}
                  </div>
                ) : documents.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center">
                    <div className="w-16 h-16 bg-slate-800/50 rounded-full flex items-center justify-center mb-4">
                      <FileText className="w-8 h-8 text-slate-500" />
                    </div>
                    <h3 className="text-white font-medium text-lg mb-1">No documents yet</h3>
                    <p className="text-slate-500 text-sm">Upload your first document to start querying.</p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3">
                    <AnimatePresence>
                      {documents.map((doc) => (
                        <motion.div
                          key={doc.doc_hash}
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, scale: 0.95 }}
                          className="group flex items-center justify-between p-4 bg-slate-800/20 hover:bg-slate-800/40 border border-slate-700/30 rounded-xl transition-all"
                        >
                          <div className="flex items-center gap-4">
                            <div className="w-10 h-10 bg-blue-500/10 rounded-lg flex items-center justify-center">
                              <FileText className="w-5 h-5 text-blue-400" />
                            </div>
                            <div>
                              <p className="text-sm font-medium text-slate-200">{doc.filename}</p>
                              <p className="text-xs text-slate-500 mt-0.5">
                                {doc.chunk_count} chunks · Uploaded {doc.ingested_at ? formatDistanceToNow(new Date(doc.ingested_at)) : 'recently'} ago
                              </p>
                            </div>
                          </div>
                          <button
                            onClick={() => handleDelete(doc.doc_hash)}
                            className="p-2 text-slate-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg opacity-0 group-hover:opacity-100 transition-all focus:opacity-100"
                            aria-label="Delete document"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                )}
              </div>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}
