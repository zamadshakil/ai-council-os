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
  const [uploadError, setUploadError] = useState<string | null>(null);

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
      setUploadError(null);
      const res = await fetch(`${API_BASE}/api/knowledge/upload`, {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'error' || data.error) {
           setUploadError(data.error || 'Failed to parse document. Check if python-docx/PyMuPDF are installed.');
        } else {
           setUploadProgress(100);
           await loadDocuments();
        }
      } else {
        setUploadError(`Server returned ${res.status}: Upload failed`);
      }
    } catch (err: any) {
      console.error('Upload failed:', err);
      setUploadError(err.message || 'Network error during upload.');
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

  

  const totalChunks = documents.reduce((acc, doc) => acc + doc.chunk_count, 0);

  return (
    <div className="space-y-12 pb-20 animate-in fade-in duration-300 ease-out fill-mode-both">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-[40px] font-bold text-[#111827] tracking-tight leading-none mb-3 flex items-center gap-3">
          <Brain className="w-10 h-10 text-indigo-600" />
          Knowledge Hub
        </h1>
        <p className="text-[15px] text-zinc-500 font-medium">Manage your organization's RAG knowledge base to contextually empower your AI workflows.</p>
      </div>

        {/* Stats Row */}
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="grid grid-cols-1 md:grid-cols-2 gap-4"
        >
          <div className="bg-white border border-zinc-200 rounded-2xl p-6 shadow-sm relative overflow-hidden">
            <div className="absolute top-0 right-0 p-4 opacity-5">
              <BookOpen className="w-24 h-24 text-indigo-900" />
            </div>
            <div className="relative z-10">
              <p className="text-sm font-medium text-zinc-500 uppercase tracking-wider mb-2">Total Documents</p>
              <p className="text-4xl font-bold text-zinc-900">{documents.length}</p>
            </div>
          </div>
          <div className="bg-white border border-zinc-200 rounded-2xl p-6 shadow-sm relative overflow-hidden">
            <div className="absolute top-0 right-0 p-4 opacity-5">
              <Brain className="w-24 h-24 text-indigo-900" />
            </div>
            <div className="relative z-10">
              <p className="text-sm font-medium text-zinc-500 uppercase tracking-wider mb-2">Total Chunks Indexed</p>
              <p className="text-4xl font-bold text-zinc-900">{totalChunks}</p>
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
              className="bg-white border border-zinc-200 rounded-2xl p-6 shadow-sm"
            >
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Upload className="w-5 h-5 text-indigo-500" /> Upload Document
              </h2>
              
              {uploadError && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-600 rounded-lg text-sm font-medium">
                  {uploadError}
                </div>
              )}
              
              <div  
                onDragOver={(e) => e.preventDefault()}
                onDrop={onDrop}
                className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-all duration-200 ${
                  uploading 
                    ? 'border-indigo-500 bg-indigo-50' 
                    : 'border-zinc-300 hover:border-indigo-400 hover:bg-zinc-50 cursor-pointer'
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
                      <Loader2 className="w-10 h-10 text-indigo-600 animate-spin" />
                      <div className="w-full">
                        <p className="text-sm font-medium text-zinc-700 mb-2">Processing Document...</p>
                        <div className="w-full h-2 bg-zinc-200 rounded-full overflow-hidden">
                          <div 
                            className="h-full bg-indigo-600 transition-all duration-300"
                            style={{ width: `${uploadProgress}%` }}
                          />
                        </div>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="w-12 h-12 bg-zinc-100 rounded-full flex items-center justify-center">
                        <Upload className="w-6 h-6 text-zinc-500" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-zinc-700">Drag & drop or click</p>
                        <p className="text-xs text-zinc-500 mt-1">Supports PDF, DOCX, TXT</p>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </motion.div>
          </div>

          {/* Right Column */}
          <div className="lg:col-span-2 flex flex-col gap-6">
            <motion.div 
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3 }}
              className="bg-white border border-zinc-200 rounded-2xl p-2 shadow-sm"
            >
              <div className="relative">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-zinc-400" />
                <input 
                  type="text"
                  placeholder="Ask a question or search documents..."
                  className="w-full bg-transparent border-none focus:ring-0 text-zinc-900 py-4 pl-12 pr-4 outline-none placeholder:text-zinc-400"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {isSearching && (
                  <Loader2 className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-indigo-500 animate-spin" />
                )}
              </div>
            </motion.div>

            <AnimatePresence mode="wait">
              {searchQuery.trim() ? (
                <motion.div 
                  key="search-results"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  className="bg-white border border-zinc-200 rounded-2xl p-6 shadow-sm"
                >
                  <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Search className="w-5 h-5 text-indigo-500" /> Search Results
                  </h2>
                  <div className="flex flex-col gap-4">
                    {searchResults.length === 0 ? (
                      <p className="text-zinc-500 text-center py-8">No matching chunks found.</p>
                    ) : (
                      searchResults.map((res, i) => (
                        <div key={i} className="p-4 bg-zinc-50 rounded-xl border border-zinc-200">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-sm font-medium text-indigo-600 flex items-center gap-1.5">
                              <FileText className="w-4 h-4" /> {res.doc_name}
                            </span>
                            <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded-full font-medium">
                              Score: {(res.score * 100).toFixed(0)}%
                            </span>
                          </div>
                          <p className="text-sm text-zinc-600 leading-relaxed">{res.text}</p>
                        </div>
                      ))
                    )}
                  </div>
                </motion.div>
              ) : (
                <motion.div 
                  key="document-list"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  className="bg-white border border-zinc-200 rounded-2xl p-6 shadow-sm"
                >
                  <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <FileText className="w-5 h-5 text-indigo-500" /> Document Repository
                  </h2>
                  
                  {loading ? (
                    <div className="py-12 flex justify-center">
                      <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
                    </div>
                  ) : documents.length === 0 ? (
                    <div className="text-center py-16">
                      <div className="w-16 h-16 bg-zinc-50 rounded-full flex items-center justify-center mx-auto mb-4">
                        <FileText className="w-8 h-8 text-zinc-300" />
                      </div>
                      <p className="text-zinc-900 font-medium mb-1">No documents yet</p>
                      <p className="text-zinc-500 text-sm">Upload your first document to start querying.</p>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-3">
                      {documents.map((doc) => (
                        <div key={doc.doc_hash} className="group flex items-center justify-between p-4 bg-zinc-50 hover:bg-zinc-100 border border-zinc-200 rounded-xl transition-colors">
                          <div className="flex items-center gap-4">
                            <div className="w-10 h-10 bg-white shadow-sm rounded-lg flex items-center justify-center">
                              <FileText className="w-5 h-5 text-indigo-600" />
                            </div>
                            <div>
                              <p className="font-medium text-zinc-900">{doc.filename}</p>
                              <div className="flex items-center gap-3 text-xs text-zinc-500 mt-1">
                                <span>{doc.chunk_count} chunks</span>
                                <span>•</span>
                                <span>{doc.ingested_at ? formatDistanceToNow(new Date(doc.ingested_at), { addSuffix: true }) : 'recently'}</span>
                              </div>
                            </div>
                          </div>
                          <button 
                            onClick={() => handleDelete(doc.doc_hash)}
                            className="p-2 text-zinc-400 hover:text-red-500 hover:bg-red-50 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
                            title="Delete Document"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
    </div>
  );
}
