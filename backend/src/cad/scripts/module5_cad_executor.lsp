; ============================================================================
; Module5 CAD-DXF executor for AcCoreConsole
; ============================================================================
; Python builds runtime .scr and calls these functions in order:
;   module5-reset
;   module5-set-plot-config
;   module5-run-frame / module5-run-sheet-set (many times)
;   module5-finalize
; ============================================================================

(vl-load-com)

(setq *m5-result-path* "")
(setq *m5-job-id* "unknown")
(setq *m5-source-dxf* "")
(setq *m5-log-path* "")

(setq *m5-output-dir* "")
(setq *m5-pc3* "打印PDF2.pc3")
(setq *m5-ctb* "monochrome.ctb")
(setq *m5-use-monochrome* T)
(setq *m5-margin-top* 20.0)
(setq *m5-margin-bottom* 10.0)
(setq *m5-margin-left* 20.0)
(setq *m5-margin-right* 10.0)
(setq *m5-bbox-margin* 0.015)
(setq *m5-retry-margin* 0.03)
(setq *m5-hard-retry-margin* 0.25)
(setq *m5-pdf-from-split-mode* "always")
(setq *m5-plot-preferred-area* "extents")
(setq *m5-plot-fallback-area* "window")
(setq *m5-split-stage-plot-enabled* nil)
(setq *m5-selection-mode* "database")
(setq *m5-db-unknown-bbox-policy* "keep_if_uncertain")
(setq *m5-db-fallback-crossing* T)

(setq *m5-frame-results* nil)
(setq *m5-sheet-results* nil)
(setq *m5-errors* nil)
(setq *m5-last-wblock-error* "")
(setq *m5-last-plot-error* "")

(defun m5-str-lower (s)
  (strcase (if s s "") T)
)

(defun m5-log (msg / fp)
  (if (and *m5-log-path* (/= *m5-log-path* ""))
    (progn
      (setq fp (open *m5-log-path* "a"))
      (if fp
        (progn
          (write-line msg fp)
          (close fp)
        )
      )
    )
  )
  (princ)
)

(defun m5-json-escape (s)
  (if (null s)
    ""
    (vl-string-subst "\\\"" "\"" (vl-string-subst "\\\\" "\\" s))
  )
)

(defun m5-file-exists (path / fp)
  (if (or (null path) (= path ""))
    nil
    (progn
      (setq fp (open path "r"))
      (if fp
        (progn
          (close fp)
          T
        )
        nil
      )
    )
  )
)

(defun m5-sleep-ms (delay-ms / start now elapsed)
  (if (and delay-ms (> delay-ms 0))
    (progn
      (setq start (getvar "MILLISECS"))
      (setq now start)
      (setq elapsed 0)
      (while (< elapsed delay-ms)
        (setq now (getvar "MILLISECS"))
        (if (>= now start)
          (setq elapsed (- now start))
          (setq elapsed (+ (- 2147483647 start) now))
        )
      )
    )
  )
  T
)

(defun m5-file-exists-retry (path retries delay-ms / i ok)
  (setq i 0)
  (setq ok nil)
  (while (and (< i retries) (not ok))
    (if (m5-file-exists path)
      (setq ok T)
      (if (and delay-ms (> delay-ms 0))
        (m5-sleep-ms delay-ms)
      )
    )
    (setq i (1+ i))
  )
  ok
)

(defun m5-bbox-expand (xmin ymin xmax ymax ratio / w h dx dy)
  (setq w (- xmax xmin))
  (setq h (- ymax ymin))
  (setq dx (* w ratio))
  (setq dy (* h ratio))
  (list (- xmin dx) (- ymin dy) (+ xmax dx) (+ ymax dy))
)

(defun m5-apply-plot-margins (bbox sx sy / xmin ymin xmax ymax ux uy)
  (setq xmin (nth 0 bbox))
  (setq ymin (nth 1 bbox))
  (setq xmax (nth 2 bbox))
  (setq ymax (nth 3 bbox))
  (setq ux sx)
  (setq uy sy)
  (if (or (null ux) (<= ux 1e-6))
    (setq ux 1.0)
  )
  (if (or (null uy) (<= uy 1e-6))
    (setq uy 1.0)
  )
  (list
    (- xmin (* *m5-margin-left* ux))
    (- ymin (* *m5-margin-bottom* uy))
    (+ xmax (* *m5-margin-right* ux))
    (+ ymax (* *m5-margin-top* uy))
  )
)

(defun m5-point-str (x y)
  (strcat (rtos x 2 8) "," (rtos y 2 8))
)

(defun m5-bbox-overlap-p (a b)
  (if (or
        (> (nth 0 a) (nth 2 b))
        (< (nth 2 a) (nth 0 b))
        (> (nth 1 a) (nth 3 b))
        (< (nth 3 a) (nth 1 b))
      )
    nil
    T
  )
)

(defun m5-safe-vla-ename (obj / ret)
  (setq ret (vl-catch-all-apply 'vlax-vla-object->ename (list obj)))
  (if (vl-catch-all-error-p ret)
    nil
    ret
  )
)

(defun m5-try-get-entity-point (ename / data pt)
  (setq data (entget ename))
  (if data
    (progn
      (setq pt (cdr (assoc 10 data)))
      (if (and pt (>= (length pt) 2))
        (list (car pt) (cadr pt))
        nil
      )
    )
    nil
  )
)

(defun m5-get-entity-bbox (obj ename / minpt maxpt ret minlst maxlst pt)
  (setq ret (vl-catch-all-apply 'vla-GetBoundingBox (list obj 'minpt 'maxpt)))
  (if (vl-catch-all-error-p ret)
    (progn
      (setq pt (if ename (m5-try-get-entity-point ename) nil))
      (if pt
        (list (car pt) (cadr pt) (car pt) (cadr pt))
        nil
      )
    )
    (progn
      (setq minlst (vlax-safearray->list (vlax-variant-value minpt)))
      (setq maxlst (vlax-safearray->list (vlax-variant-value maxpt)))
      (if (and minlst maxlst (>= (length minlst) 2) (>= (length maxlst) 2))
        (list (car minlst) (cadr minlst) (car maxlst) (cadr maxlst))
        nil
      )
    )
  )
)

(defun m5-select-by-db-bbox (bbox / acad doc space ss obj ename ent-bbox bbox-ret matched uncertain policy)
  (setq acad (vlax-get-acad-object))
  (setq doc (vla-get-ActiveDocument acad))
  (setq space (vla-get-ModelSpace doc))
  (setq ss (ssadd))
  (setq matched 0)
  (setq uncertain 0)
  (setq policy (m5-str-lower *m5-db-unknown-bbox-policy*))
  (vlax-for obj space
    (setq ename (m5-safe-vla-ename obj))
    (if ename
      (progn
        (setq bbox-ret (vl-catch-all-apply 'm5-get-entity-bbox (list obj ename)))
        (if (vl-catch-all-error-p bbox-ret)
          (setq ent-bbox nil)
          (setq ent-bbox bbox-ret)
        )
        (if ent-bbox
          (if (m5-bbox-overlap-p ent-bbox bbox)
            (progn
              (ssadd ename ss)
              (setq matched (1+ matched))
            )
          )
          (if (= policy "keep_if_uncertain")
            (progn
              (ssadd ename ss)
              (setq uncertain (1+ uncertain))
            )
          )
        )
      )
    )
  )
  (if (> (+ matched uncertain) 0)
    (progn
      (m5-log (strcat "[SELECT-DB] matched=" (itoa matched) ", uncertain=" (itoa uncertain)))
      ss
    )
    nil
  )
)

(defun m5-select-crossing (bbox / p1 p2)
  (setq p1 (list (nth 0 bbox) (nth 1 bbox)))
  (setq p2 (list (nth 2 bbox) (nth 3 bbox)))
  (ssget "_C" p1 p2)
)

(defun m5-select-crossing-polygon (verts)
  (if (and verts (>= (length verts) 4))
    (ssget "_CP" verts)
    nil
  )
)

(defun m5-select-bbox-once (bbox / mode ss db-ret)
  (setq mode (m5-str-lower *m5-selection-mode*))
  (setq ss nil)
  (if (= mode "crossing")
    (setq ss (m5-select-crossing bbox))
    (progn
      (setq db-ret (vl-catch-all-apply 'm5-select-by-db-bbox (list bbox)))
      (if (vl-catch-all-error-p db-ret)
        (progn
          (m5-log (strcat "[SELECT-DB] error=" (vl-catch-all-error-message db-ret)))
          (setq ss nil)
        )
        (setq ss db-ret)
      )
      (if (and (null ss) *m5-db-fallback-crossing*)
        (setq ss (m5-select-crossing bbox))
      )
    )
  )
  ss
)

(defun m5-select-with-retry (xmin ymin xmax ymax / bbox retry-bbox hard-retry-bbox ss)
  (setq bbox (m5-bbox-expand xmin ymin xmax ymax *m5-bbox-margin*))
  (setq ss (m5-select-bbox-once bbox))
  (if (null ss)
    (progn
      (setq retry-bbox (m5-bbox-expand xmin ymin xmax ymax *m5-retry-margin*))
      (setq ss (m5-select-bbox-once retry-bbox))
      (if (null ss)
        (progn
          ; 二次兜底：小图框可使用更大的窗口容错（由配置控制）。
          (setq hard-retry-bbox (m5-bbox-expand xmin ymin xmax ymax *m5-hard-retry-margin*))
          (setq ss (m5-select-bbox-once hard-retry-bbox))
        )
      )
    )
  )
  ss
)

(defun m5-ss-union (base extra / out i ent)
  (if base
    (setq out base)
    (setq out (ssadd))
  )
  (if extra
    (progn
      (setq i 0)
      (while (< i (sslength extra))
        (setq ent (ssname extra i))
        (if ent
          (ssadd ent out)
        )
        (setq i (1+ i))
      )
    )
  )
  out
)

(defun m5-pages-union-bbox (pages / first bbox xmin ymin xmax ymax)
  (if (null pages)
    nil
    (progn
      (setq first (car pages))
      (setq xmin (nth 1 first))
      (setq ymin (nth 2 first))
      (setq xmax (nth 3 first))
      (setq ymax (nth 4 first))
      (foreach bbox (cdr pages)
        (if (< (nth 1 bbox) xmin) (setq xmin (nth 1 bbox)))
        (if (< (nth 2 bbox) ymin) (setq ymin (nth 2 bbox)))
        (if (> (nth 3 bbox) xmax) (setq xmax (nth 3 bbox)))
        (if (> (nth 4 bbox) ymax) (setq ymax (nth 4 bbox)))
      )
      (list xmin ymin xmax ymax)
    )
  )
)

(defun m5-pt-variant (pt / arr)
  (setq arr (vlax-make-safearray vlax-vbDouble '(0 . 1)))
  (vlax-safearray-fill arr (list (car pt) (cadr pt)))
  (vlax-make-variant arr)
)

(defun m5-ss-to-variant (ss / n arr i)
  (setq n (if ss (sslength ss) 0))
  (if (<= n 0)
    nil
    (progn
      (setq arr (vlax-make-safearray vlax-vbObject (cons 0 (1- n))))
      (setq i 0)
      (while (< i n)
        (vlax-safearray-put-element arr i (vlax-ename->vla-object (ssname ss i)))
        (setq i (1+ i))
      )
      (vlax-make-variant arr)
    )
  )
)

(defun m5-make-flag-json (flag)
  (if (or (null flag) (= flag ""))
    "[]"
    (strcat "[\"" (m5-json-escape flag) "\"]")
  )
)

(defun m5-make-string-array-json (items / idx cnt out)
  (if (null items)
    "[]"
    (progn
      (setq idx 0)
      (setq cnt (length items))
      (setq out "")
      (foreach it items
        (setq idx (1+ idx))
        (setq out (strcat out "\"" (m5-json-escape it) "\""))
        (if (< idx cnt)
          (setq out (strcat out ","))
        )
      )
      (strcat "[" out "]")
    )
  )
)

(defun m5-join-json-lines (items / idx cnt out)
  (setq idx 0)
  (setq cnt (length items))
  (setq out "")
  (foreach it items
    (setq idx (1+ idx))
    (setq out (strcat out it))
    (if (< idx cnt)
      (setq out (strcat out ","))
    )
  )
  out
)

(defun module5-add-error (msg)
  (setq *m5-errors* (append *m5-errors* (list msg)))
  (m5-log (strcat "[ERROR] " msg))
)

(defun module5-add-frame-result (frame-id status pdf-path dwg-path sel-count flag / line)
  (setq line
    (strcat
      "{"
      "\"frame_id\":\"" (m5-json-escape frame-id) "\","
      "\"status\":\"" (m5-json-escape status) "\","
      "\"pdf_path\":\"" (m5-json-escape pdf-path) "\","
      "\"dwg_path\":\"" (m5-json-escape dwg-path) "\","
      "\"selection_count\":" (itoa sel-count) ","
      "\"flags\":" (m5-make-flag-json flag)
      "}"
    )
  )
  (setq *m5-frame-results* (append *m5-frame-results* (list line)))
)

(defun module5-add-sheet-result (cluster-id status pdf-path dwg-path page-count flag page-dwg-paths page-pdf-paths / line)
  (setq line
    (strcat
      "{"
      "\"cluster_id\":\"" (m5-json-escape cluster-id) "\","
      "\"status\":\"" (m5-json-escape status) "\","
      "\"pdf_path\":\"" (m5-json-escape pdf-path) "\","
      "\"dwg_path\":\"" (m5-json-escape dwg-path) "\","
      "\"page_count\":" (itoa page-count) ","
      "\"flags\":" (m5-make-flag-json flag) ","
      "\"page_dwg_paths\":" (m5-make-string-array-json page-dwg-paths) ","
      "\"page_pdf_paths\":" (m5-make-string-array-json page-pdf-paths)
      "}"
    )
  )
  (setq *m5-sheet-results* (append *m5-sheet-results* (list line)))
)

(defun m5-write-result-json (/ fp frame-json sheet-json errors-json idx cnt)
  (setq fp (open *m5-result-path* "w"))
  (if (not fp)
    (progn
      (m5-log (strcat "[ERROR] cannot write result file: " *m5-result-path*))
    )
    (progn
      (setq frame-json (m5-join-json-lines *m5-frame-results*))
      (setq sheet-json (m5-join-json-lines *m5-sheet-results*))
      (setq errors-json "")
      (if *m5-errors*
        (progn
          (setq idx 0)
          (setq cnt (length *m5-errors*))
          (foreach e *m5-errors*
            (setq idx (1+ idx))
            (setq errors-json (strcat errors-json "\"" (m5-json-escape e) "\""))
            (if (< idx cnt)
              (setq errors-json (strcat errors-json ","))
            )
          )
        )
      )
      (write-line "{" fp)
      (write-line "  \"schema_version\": \"cad-dxf-result@1.0\"," fp)
      (write-line (strcat "  \"job_id\": \"" (m5-json-escape *m5-job-id*) "\"," ) fp)
      (write-line (strcat "  \"source_dxf\": \"" (m5-json-escape *m5-source-dxf*) "\"," ) fp)
      (write-line (strcat "  \"frames\": [" frame-json "],") fp)
      (write-line (strcat "  \"sheet_sets\": [" sheet-json "],") fp)
      (write-line (strcat "  \"errors\": [" errors-json "]") fp)
      (write-line "}" fp)
      (close fp)
    )
  )
)

(defun m5-set-system-vars ()
  (setvar "FILEDIA" 0)
  (setvar "CMDDIA" 0)
  (setvar "SAVEFIDELITY" 0)
  (setvar "BACKGROUNDPLOT" 0)
  (setvar "TILEMODE" 1)
)

(defun m5-media-name (paper-w paper-h / w h)
  (setq w (abs paper-w))
  (setq h (abs paper-h))
  (cond
    ((and (< (abs (- w 1189.0)) 10.0) (< (abs (- h 841.0)) 10.0)) "ISO_A0_(1189.00_x_841.00_MM)")
    ((and (< (abs (- w 841.0)) 10.0) (< (abs (- h 1189.0)) 10.0)) "ISO_A0_(841.00_x_1189.00_MM)")
    ((and (< (abs (- w 841.0)) 10.0) (< (abs (- h 594.0)) 10.0)) "ISO_A1_(841.00_x_594.00_MM)")
    ((and (< (abs (- w 594.0)) 10.0) (< (abs (- h 841.0)) 10.0)) "ISO_A1_(594.00_x_841.00_MM)")
    ((and (< (abs (- w 594.0)) 10.0) (< (abs (- h 420.0)) 10.0)) "ISO_A2_(594.00_x_420.00_MM)")
    ((and (< (abs (- w 420.0)) 10.0) (< (abs (- h 594.0)) 10.0)) "ISO_A2_(420.00_x_594.00_MM)")
    ((and (< (abs (- w 420.0)) 10.0) (< (abs (- h 297.0)) 10.0)) "ISO_A3_(420.00_x_297.00_MM)")
    ((and (< (abs (- w 297.0)) 10.0) (< (abs (- h 420.0)) 10.0)) "ISO_A3_(297.00_x_420.00_MM)")
    ((and (< (abs (- w 297.0)) 10.0) (< (abs (- h 210.0)) 10.0)) "ISO_A4_(297.00_x_210.00_MM)")
    ((and (< (abs (- w 210.0)) 10.0) (< (abs (- h 297.0)) 10.0)) "ISO_A4_(210.00_x_297.00_MM)")
    (T "ISO_A1_(841.00_x_594.00_MM)")
  )
)

(defun m5-orientation-name (paper-w paper-h)
  (if (>= paper-w paper-h) "Landscape" "Portrait")
)

(defun m5-do-wblock (dwg-path ss / cmd-ret)
  (setq *m5-last-wblock-error* "")
  (if (or (null ss) (= (sslength ss) 0))
    nil
    (progn
      ; AcCoreConsole 下显式传入 ss 兼容性较差，稳定路径仍使用 "_P"（已通过前置 sssetfirst 固定上下文）。
      (sssetfirst nil ss)
      (setq cmd-ret (vl-catch-all-apply 'command-s (list "_.-WBLOCK" dwg-path "0,0,0" "_P" "")))
      (if (vl-catch-all-error-p cmd-ret)
        (progn
          (setq *m5-last-wblock-error* (vl-catch-all-error-message cmd-ret))
          nil
        )
        (m5-file-exists-retry dwg-path 15 100)
      )
    )
  )
)

(defun m5-is-a0-paper (paper-w paper-h / w h)
  (setq w (abs paper-w))
  (setq h (abs paper-h))
  (or
    (and (< (abs (- w 1189.0)) 10.0) (< (abs (- h 841.0)) 10.0))
    (and (< (abs (- w 841.0)) 10.0) (< (abs (- h 1189.0)) 10.0))
  )
)

(defun m5-do-plot-once (pdf-path bbox media orient area-mode / p1 p2 cmd-ret mode)
  (setq mode (strcase (if area-mode area-mode "W")))
  (setq p1 (m5-point-str (nth 0 bbox) (nth 1 bbox)))
  (setq p2 (m5-point-str (nth 2 bbox) (nth 3 bbox)))
  (if (= mode "E")
    (setq cmd-ret
      (vl-catch-all-apply
        'command-s
        (list
          "_.-PLOT"
          "Y"
          ""
          *m5-pc3*
          media
          "M"
          orient
          "N"
          "E"
          "F"
          "C"
          "Y"
          *m5-ctb*
          "Y"
          "A"
          pdf-path
          "N"
          "Y"
        )
      )
    )
    (setq cmd-ret
      (vl-catch-all-apply
        'command-s
        (list
          "_.-PLOT"
          "Y"
          ""
          *m5-pc3*
          media
          "M"
          orient
          "N"
          "W"
          p1
          p2
          "F"
          "C"
          "Y"
          *m5-ctb*
          "Y"
          "A"
          pdf-path
          "N"
          "Y"
        )
      )
    )
  )
  (if (vl-catch-all-error-p cmd-ret)
    (progn
      (setq *m5-last-plot-error* (strcat "PLOT_COMMAND_ERROR:" (vl-catch-all-error-message cmd-ret)))
      nil
    )
    (if (m5-file-exists-retry pdf-path 10 100)
      (progn
        (setq *m5-last-plot-error* "")
        T
      )
      (progn
        (setq *m5-last-plot-error* (strcat "PLOT_OUTPUT_MISSING:" media ":" mode))
        nil
      )
    )
  )
)

(defun m5-do-plot-with-area (pdf-path bbox paper-w paper-h area-mode / media1 media2 orient1 orient2 ok)
  (setq *m5-last-plot-error* "")
  (setq media1 (m5-media-name paper-w paper-h))
  (setq media2 (m5-media-name paper-h paper-w))
  (setq orient1 (m5-orientation-name paper-w paper-h))
  (setq orient2 (m5-orientation-name paper-h paper-w))

  (setq ok (m5-do-plot-once pdf-path bbox media1 orient1 area-mode))

  ; A0在不同驱动上常见 media 名差异，优先尝试 expand（可保留页边距语义）。
  (if (and (not ok) (m5-is-a0-paper paper-w paper-h))
    (setq ok (m5-do-plot-once pdf-path bbox "ISO_expand_A0_(1219.00_x_871.00_MM)" "Landscape" area-mode))
  )
  (if (and (not ok) (m5-is-a0-paper paper-w paper-h))
    (setq ok (m5-do-plot-once pdf-path bbox "ISO_expand_A0_(871.00_x_1219.00_MM)" "Portrait" area-mode))
  )
  (if (and (not ok) (m5-is-a0-paper paper-w paper-h))
    (setq ok (m5-do-plot-once pdf-path bbox "ISO_expand_A0_(1189.00_x_841.00_MM)" "Landscape" area-mode))
  )
  (if (and (not ok) (m5-is-a0-paper paper-w paper-h))
    (setq ok (m5-do-plot-once pdf-path bbox "ISO_expand_A0_(1189.00_x_841.00_MM)" "Portrait" area-mode))
  )
  (if (and (not ok) (m5-is-a0-paper paper-w paper-h))
    (setq ok (m5-do-plot-once pdf-path bbox "ISO_expand_A0_(841.00_x_1189.00_MM)" "Landscape" area-mode))
  )
  (if (and (not ok) (m5-is-a0-paper paper-w paper-h))
    (setq ok (m5-do-plot-once pdf-path bbox "ISO_expand_A0_(841.00_x_1189.00_MM)" "Portrait" area-mode))
  )

  (if (and (not ok) (/= orient2 orient1))
    (setq ok (m5-do-plot-once pdf-path bbox media1 orient2 area-mode))
  )

  (if (and (not ok) (/= media2 media1))
    (setq ok (m5-do-plot-once pdf-path bbox media2 orient1 area-mode))
  )

  (if (and (not ok) (/= media2 media1) (/= orient2 orient1))
    (setq ok (m5-do-plot-once pdf-path bbox media2 orient2 area-mode))
  )

  ok
)

(defun m5-do-plot (pdf-path bbox paper-w paper-h)
  (m5-do-plot-with-area pdf-path bbox paper-w paper-h "W")
)

(defun m5-do-plot-from-split-dwg (pdf-path bbox paper-w paper-h / preferred fallback ok used-flag)
  (setq preferred (m5-str-lower *m5-plot-preferred-area*))
  (setq fallback (m5-str-lower *m5-plot-fallback-area*))
  (setq ok nil)
  (setq used-flag "")

  (if (= preferred "extents")
    (progn
      (setq ok (m5-do-plot-with-area pdf-path bbox paper-w paper-h "E"))
      (if ok (setq used-flag "PLOT_EXTENTS_USED"))
    )
    (progn
      (setq ok (m5-do-plot-with-area pdf-path bbox paper-w paper-h "W"))
      (if ok (setq used-flag "PLOT_WINDOW_USED"))
    )
  )

  (if (and (not ok) (= fallback "window") (/= preferred "window"))
    (progn
      (setq ok (m5-do-plot-with-area pdf-path bbox paper-w paper-h "W"))
      (if ok (setq used-flag "PLOT_WINDOW_FALLBACK"))
    )
  )

  (if ok
    (list T used-flag)
    (list nil "PLOT_FAILED")
  )
)

(defun module5-reset (result-path job-id source-dxf log-path)
  (setq *m5-result-path* result-path)
  (setq *m5-job-id* job-id)
  (setq *m5-source-dxf* source-dxf)
  (setq *m5-log-path* log-path)
  (setq *m5-frame-results* nil)
  (setq *m5-sheet-results* nil)
  (setq *m5-errors* nil)
  (setq *m5-last-wblock-error* "")
  (setq *m5-last-plot-error* "")
  (setq *m5-pdf-from-split-mode* "always")
  (setq *m5-plot-preferred-area* "extents")
  (setq *m5-plot-fallback-area* "window")
  (setq *m5-split-stage-plot-enabled* nil)
  (setq *m5-selection-mode* "database")
  (setq *m5-db-unknown-bbox-policy* "keep_if_uncertain")
  (setq *m5-db-fallback-crossing* T)
  (setq *m5-hard-retry-margin* 0.25)
  (m5-set-system-vars)
  (m5-log (strcat "[START] job=" job-id " source=" source-dxf))
  (princ)
)

(defun module5-set-plot-config
  (output-dir pc3 ctb use-mono margin-top margin-bottom margin-left margin-right bbox-margin retry-margin)
  (setq *m5-output-dir* output-dir)
  (setq *m5-pc3* pc3)
  (setq *m5-ctb* ctb)
  (setq *m5-use-monochrome* use-mono)
  (setq *m5-margin-top* margin-top)
  (setq *m5-margin-bottom* margin-bottom)
  (setq *m5-margin-left* margin-left)
  (setq *m5-margin-right* margin-right)
  (setq *m5-bbox-margin* bbox-margin)
  (setq *m5-retry-margin* retry-margin)
  (m5-log (strcat "[CFG] output=" output-dir ", pc3=" pc3 ", ctb=" ctb))
  (princ)
)

(defun module5-set-selection-config
  (selection-mode hard-retry-margin db-unknown-bbox-policy db-fallback-crossing)
  (setq *m5-selection-mode* (if selection-mode selection-mode "database"))
  (setq *m5-hard-retry-margin* (if (and hard-retry-margin (> hard-retry-margin 0.0)) hard-retry-margin 0.25))
  (setq *m5-db-unknown-bbox-policy*
    (if db-unknown-bbox-policy db-unknown-bbox-policy "keep_if_uncertain")
  )
  (setq *m5-db-fallback-crossing* db-fallback-crossing)
  (m5-log
    (strcat
      "[CFG] selection_mode="
      *m5-selection-mode*
      ", hard_retry_margin="
      (rtos *m5-hard-retry-margin* 2 6)
      ", unknown_bbox_policy="
      *m5-db-unknown-bbox-policy*
      ", db_fallback_crossing="
      (if *m5-db-fallback-crossing* "true" "false")
    )
  )
  (princ)
)

(defun module5-set-output-config
  (pdf-from-split-mode preferred-area fallback-area split-stage-plot-enabled)
  (setq *m5-pdf-from-split-mode* pdf-from-split-mode)
  (setq *m5-plot-preferred-area* preferred-area)
  (setq *m5-plot-fallback-area* fallback-area)
  (setq *m5-split-stage-plot-enabled* split-stage-plot-enabled)
  (m5-log
    (strcat
      "[CFG] output_mode="
      pdf-from-split-mode
      ", preferred="
      preferred-area
      ", fallback="
      fallback-area
      ", split_plot_enabled="
      (if split-stage-plot-enabled "true" "false")
    )
  )
  (princ)
)

(defun module5-run-frame-split
  (frame-id name xmin ymin xmax ymax vx1 vy1 vx2 vy2 vx3 vy3 vx4 vy4 frame-sx frame-sy paper-w paper-h / verts ss sel-count dwg-path ok-w)
  (setq ss (m5-select-with-retry xmin ymin xmax ymax))
  (if (null ss)
    (progn
      (setq verts (list
        (list vx1 vy1)
        (list vx2 vy2)
        (list vx3 vy3)
        (list vx4 vy4)
      ))
      (setq ss (m5-select-crossing-polygon verts))
    )
  )

  (if (null ss)
    (progn
      (module5-add-frame-result frame-id "failed" "" "" 0 "CAD_EMPTY_SELECTION")
      (m5-log (strcat "[FRAME-SPLIT] failed empty selection: " frame-id))
    )
    (progn
      (setq sel-count (sslength ss))
      (setq dwg-path (strcat *m5-output-dir* "\\" name ".dwg"))
      (setq ok-w (vl-catch-all-apply 'm5-do-wblock (list dwg-path ss)))
      (if (vl-catch-all-error-p ok-w)
        (progn
          (setq *m5-last-wblock-error* (vl-catch-all-error-message ok-w))
          (setq ok-w nil)
        )
      )
      (if ok-w
        (progn
          (module5-add-frame-result frame-id "ok" "" dwg-path sel-count "")
          (m5-log (strcat "[FRAME-SPLIT] ok: " frame-id ", dwg=" dwg-path))
        )
        (progn
          (module5-add-frame-result frame-id "failed" "" dwg-path sel-count "WBLOCK_FAILED")
          (m5-log (strcat "[FRAME-SPLIT] failed: " frame-id ", err=" *m5-last-wblock-error*))
        )
      )
    )
  )
  (princ)
)

(defun module5-run-frame-plot-from-split
  (frame-id name xmin ymin xmax ymax vx1 vy1 vx2 vy2 vx3 vy3 vx4 vy4 frame-sx frame-sy paper-w paper-h / bbox pdf-path plot-bbox plot-sx plot-sy plot-ret ok-p plot-flag)
  (setq bbox (list xmin ymin xmax ymax))
  (setq pdf-path (strcat *m5-output-dir* "\\" name ".pdf"))
  (setq plot-sx frame-sx)
  (setq plot-sy frame-sy)
  (if (or (null plot-sx) (<= plot-sx 1e-6))
    (if (> paper-w 1e-6)
      (setq plot-sx (/ (- xmax xmin) paper-w))
      (setq plot-sx 1.0)
    )
  )
  (if (or (null plot-sy) (<= plot-sy 1e-6))
    (if (> paper-h 1e-6)
      (setq plot-sy (/ (- ymax ymin) paper-h))
      (setq plot-sy 1.0)
    )
  )
  (setq plot-bbox (m5-apply-plot-margins bbox plot-sx plot-sy))
  (setq plot-ret (vl-catch-all-apply 'm5-do-plot-from-split-dwg (list pdf-path plot-bbox paper-w paper-h)))
  (if (vl-catch-all-error-p plot-ret)
    (progn
      (setq ok-p nil)
      (setq plot-flag "PLOT_FAILED")
      (setq *m5-last-plot-error* (vl-catch-all-error-message plot-ret))
    )
    (progn
      (setq ok-p (car plot-ret))
      (setq plot-flag (cadr plot-ret))
    )
  )
  (if ok-p
    (progn
      (module5-add-frame-result frame-id "ok" pdf-path *m5-source-dxf* 1 plot-flag)
      (m5-log (strcat "[FRAME-PLOT] ok: " frame-id ", flag=" plot-flag ", pdf=" pdf-path))
    )
    (progn
      (module5-add-frame-result frame-id "failed" pdf-path *m5-source-dxf* 1 plot-flag)
      (m5-log (strcat "[FRAME-PLOT] failed: " frame-id ", flag=" plot-flag ", err=" *m5-last-plot-error*))
    )
  )
  (princ)
)

(defun module5-run-frame-plot-window
  (frame-id name xmin ymin xmax ymax vx1 vy1 vx2 vy2 vx3 vy3 vx4 vy4 frame-sx frame-sy paper-w paper-h / bbox pdf-path plot-bbox plot-sx plot-sy ok-p)
  (setq bbox (list xmin ymin xmax ymax))
  (setq pdf-path (strcat *m5-output-dir* "\\" name ".pdf"))
  (setq plot-sx frame-sx)
  (setq plot-sy frame-sy)
  (if (or (null plot-sx) (<= plot-sx 1e-6))
    (if (> paper-w 1e-6)
      (setq plot-sx (/ (- xmax xmin) paper-w))
      (setq plot-sx 1.0)
    )
  )
  (if (or (null plot-sy) (<= plot-sy 1e-6))
    (if (> paper-h 1e-6)
      (setq plot-sy (/ (- ymax ymin) paper-h))
      (setq plot-sy 1.0)
    )
  )
  (setq plot-bbox (m5-apply-plot-margins bbox plot-sx plot-sy))
  (setq ok-p (vl-catch-all-apply 'm5-do-plot (list pdf-path plot-bbox paper-w paper-h)))
  (if (vl-catch-all-error-p ok-p)
    (progn
      (setq *m5-last-plot-error* (vl-catch-all-error-message ok-p))
      (setq ok-p nil)
    )
  )
  (if ok-p
    (progn
      (module5-add-frame-result frame-id "ok" pdf-path *m5-source-dxf* 1 "PLOT_WINDOW_USED")
      (m5-log (strcat "[FRAME-PLOT-WINDOW] ok: " frame-id ", pdf=" pdf-path))
    )
    (progn
      (module5-add-frame-result frame-id "failed" pdf-path *m5-source-dxf* 1 "PLOT_WINDOW_FAILED")
      (m5-log (strcat "[FRAME-PLOT-WINDOW] failed: " frame-id ", err=" *m5-last-plot-error*))
    )
  )
  (princ)
)

(defun module5-run-sheet-set-split
  (cluster-id name pages paper-w paper-h page-count / ss page page-ss verts union-bbox sel-count dwg-path pdf-path ok-w page-dwgs page-dwg page-index page-ok page-partial)
  (setq ss nil)
  (foreach page pages
    (if (and page (>= (length page) 5))
      (progn
        (setq page-ss (m5-select-with-retry (nth 1 page) (nth 2 page) (nth 3 page) (nth 4 page)))
        (if (and (null page-ss) (>= (length page) 13))
          (progn
            (setq verts (list
              (list (nth 5 page) (nth 6 page))
              (list (nth 7 page) (nth 8 page))
              (list (nth 9 page) (nth 10 page))
              (list (nth 11 page) (nth 12 page))
            ))
            (setq page-ss (m5-select-crossing-polygon verts))
          )
        )
        (if page-ss
          (setq ss (m5-ss-union ss page-ss))
        )
      )
    )
  )

  (if (null ss)
    (progn
      (module5-add-sheet-result cluster-id "failed" "" "" page-count "CAD_EMPTY_SELECTION" nil nil)
      (m5-log (strcat "[SHEET-SPLIT] failed empty selection: " cluster-id))
    )
    (progn
      (setq union-bbox (m5-pages-union-bbox pages))
      (if union-bbox
        (progn
          (setq page-ss (m5-select-with-retry (nth 0 union-bbox) (nth 1 union-bbox) (nth 2 union-bbox) (nth 3 union-bbox)))
          (if (null page-ss)
            (progn
              (setq verts (list
                (list (nth 0 union-bbox) (nth 1 union-bbox))
                (list (nth 2 union-bbox) (nth 1 union-bbox))
                (list (nth 2 union-bbox) (nth 3 union-bbox))
                (list (nth 0 union-bbox) (nth 3 union-bbox))
              ))
              (setq page-ss (m5-select-crossing-polygon verts))
            )
          )
          (if page-ss
            (setq ss page-ss)
          )
        )
      )
      (setq sel-count (sslength ss))
      (setq dwg-path (strcat *m5-output-dir* "\\" name ".dwg"))
      (setq pdf-path (strcat *m5-output-dir* "\\" name ".pdf"))
      (setq ok-w (vl-catch-all-apply 'm5-do-wblock (list dwg-path ss)))
      (if (vl-catch-all-error-p ok-w)
        (progn
          (setq *m5-last-wblock-error* (vl-catch-all-error-message ok-w))
          (setq ok-w nil)
        )
      )

      (setq page-dwgs nil)
      (setq page-partial nil)
      (foreach page pages
        (if (and page (>= (length page) 5))
          (progn
            (setq page-index (fix (nth 0 page)))
            (setq page-ss (m5-select-with-retry (nth 1 page) (nth 2 page) (nth 3 page) (nth 4 page)))
            (if (and (null page-ss) (>= (length page) 13))
              (progn
                (setq verts (list
                  (list (nth 5 page) (nth 6 page))
                  (list (nth 7 page) (nth 8 page))
                  (list (nth 9 page) (nth 10 page))
                  (list (nth 11 page) (nth 12 page))
                ))
                (setq page-ss (m5-select-crossing-polygon verts))
              )
            )
            (if page-ss
              (progn
                (setq page-dwg (strcat *m5-output-dir* "\\" name "__p" (itoa page-index) ".dwg"))
                (setq page-ok (vl-catch-all-apply 'm5-do-wblock (list page-dwg page-ss)))
                (if (vl-catch-all-error-p page-ok)
                  (setq page-ok nil)
                )
                (if page-ok
                  (setq page-dwgs (append page-dwgs (list page-dwg)))
                  (setq page-partial T)
                )
              )
              (setq page-partial T)
            )
          )
        )
      )

      (if (and ok-w (= (length page-dwgs) page-count) (not page-partial))
        (progn
          (module5-add-sheet-result cluster-id "ok" pdf-path dwg-path page-count "" page-dwgs nil)
          (m5-log
            (strcat "[SHEET-SPLIT] ok: " cluster-id ", dwg=" dwg-path ", page_dwgs=" (itoa (length page-dwgs)))
          )
        )
        (progn
          (module5-add-sheet-result
            cluster-id
            "failed"
            pdf-path
            dwg-path
            page-count
            (if ok-w "A4_PAGE_WBLOCK_PARTIAL" "WBLOCK_FAILED")
            page-dwgs
            nil
          )
          (m5-log (strcat "[SHEET-SPLIT] failed: " cluster-id ", page_dwgs=" (itoa (length page-dwgs))))
        )
      )
    )
  )
  (princ)
)

(defun module5-run-frame
  (frame-id name xmin ymin xmax ymax vx1 vy1 vx2 vy2 vx3 vy3 vx4 vy4 frame-sx frame-sy paper-w paper-h / bbox verts ss sel-count dwg-path pdf-path plot-bbox plot-sx plot-sy ok-w ok-p)
  (setq bbox (m5-bbox-expand xmin ymin xmax ymax *m5-bbox-margin*))
  (setq ss (m5-select-with-retry xmin ymin xmax ymax))
  (if (null ss)
    (progn
      (setq verts (list
        (list vx1 vy1)
        (list vx2 vy2)
        (list vx3 vy3)
        (list vx4 vy4)
      ))
      (setq ss (m5-select-crossing-polygon verts))
    )
  )

  (if (null ss)
    (progn
      (module5-add-frame-result frame-id "failed" "" "" 0 "CAD_EMPTY_SELECTION")
      (m5-log (strcat "[FRAME] failed empty selection: " frame-id))
    )
    (progn
      (setq sel-count (sslength ss))
      (setq dwg-path (strcat *m5-output-dir* "\\" name ".dwg"))
      (setq pdf-path (strcat *m5-output-dir* "\\" name ".pdf"))
      (setq ok-w (vl-catch-all-apply 'm5-do-wblock (list dwg-path ss)))
      (if (vl-catch-all-error-p ok-w)
        (progn
          (setq *m5-last-wblock-error* (vl-catch-all-error-message ok-w))
          (setq ok-w nil)
        )
      )
      (setq plot-sx frame-sx)
      (setq plot-sy frame-sy)
      (if (or (null plot-sx) (<= plot-sx 1e-6))
        (if (> paper-w 1e-6)
          (setq plot-sx (/ (- xmax xmin) paper-w))
          (setq plot-sx 1.0)
        )
      )
      (if (or (null plot-sy) (<= plot-sy 1e-6))
        (if (> paper-h 1e-6)
          (setq plot-sy (/ (- ymax ymin) paper-h))
          (setq plot-sy 1.0)
        )
      )
      (setq plot-bbox (m5-apply-plot-margins bbox plot-sx plot-sy))
      (setq ok-p (vl-catch-all-apply 'm5-do-plot (list pdf-path plot-bbox paper-w paper-h)))
      (if (vl-catch-all-error-p ok-p)
        (progn
          (setq *m5-last-plot-error* (vl-catch-all-error-message ok-p))
          (setq ok-p nil)
        )
      )
      (m5-log
        (strcat
          "[FRAME] "
          frame-id
          " wblock="
          (if ok-w "ok" "fail")
          " plot="
          (if ok-p "ok" "fail")
          " wblock_err="
          *m5-last-wblock-error*
          " plot_err="
          *m5-last-plot-error*
          " dwg="
          dwg-path
          " pdf="
          pdf-path
        )
      )
      (if (and ok-w ok-p)
        (progn
          (module5-add-frame-result frame-id "ok" pdf-path dwg-path sel-count "")
          (m5-log (strcat "[FRAME] ok: " frame-id))
        )
        (progn
          (module5-add-frame-result
            frame-id
            "failed"
            pdf-path
            dwg-path
            sel-count
            (if ok-w "PLOT_FAILED" "WBLOCK_FAILED")
          )
          (m5-log (strcat "[FRAME] failed export: " frame-id))
        )
      )
    )
  )
  (princ)
)

(defun module5-run-sheet-set
  (cluster-id name pages paper-w paper-h page-count / ss page page-ss verts union-bbox sel-count dwg-path pdf-path page-pdf page-pdfs page-index page-bbox page-plot-bbox page-sx page-sy ok-this-page any-plot-fail ok-w ok-p)
  (setq ss nil)
  (foreach page pages
    (if (and page (>= (length page) 5))
      (progn
        (setq page-ss (m5-select-with-retry (nth 1 page) (nth 2 page) (nth 3 page) (nth 4 page)))
        (if (and (null page-ss) (>= (length page) 13))
          (progn
            (setq verts (list
              (list (nth 5 page) (nth 6 page))
              (list (nth 7 page) (nth 8 page))
              (list (nth 9 page) (nth 10 page))
              (list (nth 11 page) (nth 12 page))
            ))
            (setq page-ss (m5-select-crossing-polygon verts))
          )
        )
        (if page-ss
          (setq ss (m5-ss-union ss page-ss))
        )
      )
    )
  )
  (if (null ss)
    (progn
      (module5-add-sheet-result cluster-id "failed" "" "" page-count "CAD_EMPTY_SELECTION" nil nil)
      (m5-log (strcat "[SHEET] failed empty selection: " cluster-id))
    )
    (progn
      ; A4 组关键修复：为 WBLOCK 再做一次“并集外包框”选集，
      ; 让后续 -WBLOCK 的 "_P" 明确指向整组并集，而非最后一页选集。
      (setq union-bbox (m5-pages-union-bbox pages))
      (if union-bbox
        (progn
          (setq page-ss (m5-select-with-retry (nth 0 union-bbox) (nth 1 union-bbox) (nth 2 union-bbox) (nth 3 union-bbox)))
          (if (null page-ss)
            (progn
              (setq verts (list
                (list (nth 0 union-bbox) (nth 1 union-bbox))
                (list (nth 2 union-bbox) (nth 1 union-bbox))
                (list (nth 2 union-bbox) (nth 3 union-bbox))
                (list (nth 0 union-bbox) (nth 3 union-bbox))
              ))
              (setq page-ss (m5-select-crossing-polygon verts))
            )
          )
          (if page-ss
            (progn
              (setq ss page-ss)
              (m5-log (strcat "[SHEET] union reselection ok, count=" (itoa (sslength page-ss))))
            )
            (m5-log "[SHEET] union reselection empty, fallback to page-union ss")
          )
        )
      )
      (setq sel-count (sslength ss))
      (setq dwg-path (strcat *m5-output-dir* "\\" name ".dwg"))
      (setq pdf-path (strcat *m5-output-dir* "\\" name ".pdf"))
      (setq ok-w (vl-catch-all-apply 'm5-do-wblock (list dwg-path ss)))
      (if (vl-catch-all-error-p ok-w)
        (progn
          (setq *m5-last-wblock-error* (vl-catch-all-error-message ok-w))
          (setq ok-w nil)
        )
      )
      (setq page-pdfs nil)
      (setq any-plot-fail nil)
      (foreach page pages
        (if (and page (>= (length page) 5))
          (progn
            (setq page-index (fix (nth 0 page)))
            (setq page-bbox (list (nth 1 page) (nth 2 page) (nth 3 page) (nth 4 page)))
            (setq page-sx (if (>= (length page) 15) (nth 13 page) nil))
            (setq page-sy (if (>= (length page) 15) (nth 14 page) nil))
            (if (or (null page-sx) (<= page-sx 1e-6))
              (if (> paper-w 1e-6)
                (setq page-sx (/ (- (nth 2 page-bbox) (nth 0 page-bbox)) paper-w))
                (setq page-sx 1.0)
              )
            )
            (if (or (null page-sy) (<= page-sy 1e-6))
              (if (> paper-h 1e-6)
                (setq page-sy (/ (- (nth 3 page-bbox) (nth 1 page-bbox)) paper-h))
                (setq page-sy 1.0)
              )
            )
            (setq page-plot-bbox (m5-apply-plot-margins page-bbox page-sx page-sy))
            (setq page-pdf (strcat *m5-output-dir* "\\" name "__p" (itoa page-index) ".pdf"))
            (setq ok-this-page (vl-catch-all-apply 'm5-do-plot (list page-pdf page-plot-bbox paper-w paper-h)))
            (if (vl-catch-all-error-p ok-this-page)
              (progn
                (setq *m5-last-plot-error* (vl-catch-all-error-message ok-this-page))
                (setq ok-this-page nil)
              )
            )
            (if ok-this-page
              (setq page-pdfs (append page-pdfs (list page-pdf)))
              (setq any-plot-fail T)
            )
          )
        )
      )
      (setq ok-p (and (not any-plot-fail) (> (length page-pdfs) 0)))
      (m5-log
        (strcat
          "[SHEET] "
          cluster-id
          " wblock="
          (if ok-w "ok" "fail")
          " plot="
          (if ok-p "ok" "fail")
          " wblock_err="
          *m5-last-wblock-error*
          " plot_err="
          *m5-last-plot-error*
          " dwg="
          dwg-path
          " pdf="
          pdf-path
          " sel_count="
          (itoa sel-count)
          " page_pdfs="
          (itoa (length page-pdfs))
        )
      )
      (if (and ok-w ok-p (> (length page-pdfs) 0))
        (progn
          (module5-add-sheet-result cluster-id "failed" pdf-path dwg-path page-count "PLOT_MERGE_REQUIRED" nil page-pdfs)
          (m5-log (strcat "[SHEET] pending merge: " cluster-id ", pages=" (itoa page-count)))
        )
        (progn
          (module5-add-sheet-result
            cluster-id
            "failed"
            pdf-path
            dwg-path
            page-count
            (if ok-w "PLOT_FAILED" "WBLOCK_FAILED")
            nil
            page-pdfs
          )
          (m5-log (strcat "[SHEET] failed export: " cluster-id))
        )
      )
    )
  )
  (princ)
)

(defun module5-finalize ()
  (m5-write-result-json)
  (m5-log "[DONE] module5-finalize")
  (princ)
)

(princ)
