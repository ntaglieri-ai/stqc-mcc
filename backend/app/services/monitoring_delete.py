"""Permanent deletion of selected event records and their embedded report data."""
from fastapi import HTTPException
from datetime import timedelta
from backend.app.models.commessa import (
    AssemblyScanEvent, PieceScanEvent, PieceWorkSession, ProgettazioneEvento,
    ScannerPhaseEvent, WeldingScanEvent, WorkshopScanAttempt, WorkshopScanBlock,
)
from backend.app.models.warehouse import StockMovement, WarehouseChangeRequest, WarehouseItem

EVENT_MODELS = {model.__tablename__: model for model in (
    AssemblyScanEvent, PieceScanEvent, ProgettazioneEvento, ScannerPhaseEvent,
    WeldingScanEvent, WorkshopScanAttempt, StockMovement, WarehouseChangeRequest,
)}


def _delete_piece_event(db, event):
    # Session references are plain integer pointers, not cascading relationships.
    db.query(PieceWorkSession).filter_by(open_event_id=event.id).update(
        {PieceWorkSession.open_event_id: None}, synchronize_session='fetch')
    db.query(PieceWorkSession).filter_by(close_event_id=event.id).update(
        {PieceWorkSession.close_event_id: None}, synchronize_session='fetch')
    db.delete(event)


def delete_event(db, source):
    table, event_id = source
    model = EVENT_MODELS.get(table)
    if model is None:
        raise HTTPException(422, 'Tipo evento non cancellabile')
    row = db.get(model, event_id)
    if row is None:
        raise HTTPException(409, 'Evento già cancellato. Aggiorna il registro.')
    if isinstance(row, WorkshopScanAttempt) and row.outcome == 'OK':
        mirrors = db.query(PieceScanEvent)
        if row.scan_block_id and row.scan_kind in {'PIECE', 'WORKSTATION_END'}:
            mirrors = mirrors.filter(PieceScanEvent.scan_block_id == row.scan_block_id)
            if row.scan_kind == 'PIECE':
                mirrors = mirrors.filter(PieceScanEvent.piece_id == row.piece_id,
                    PieceScanEvent.event_type.in_(['PHASE_START', 'PHASE_DONE']))
            else:
                mirrors = mirrors.filter(PieceScanEvent.event_type == 'PHASE_END')
            for mirror in mirrors.all():
                _delete_piece_event(db, mirror)
        elif row.piece_id and row.scan_kind in {
            'PIECE_READ', 'PREPROD_PIECE_ASSIGNED', 'PREPROD_PIECE_PENDING',
        }:
            event_type = {'PIECE_READ': 'PIECE_READ',
                'PREPROD_PIECE_ASSIGNED': 'MATERIAL_ASSIGNED',
                'PREPROD_PIECE_PENDING': 'MATERIAL_PENDING'}[row.scan_kind]
            candidates = mirrors.filter(PieceScanEvent.piece_id == row.piece_id,
                PieceScanEvent.scanner_device_id == row.scanner_device_id,
                PieceScanEvent.event_type == event_type).all()
            linked = [e for e in candidates if (e.metadata_json or {}).get('scan_attempt_id') == row.id]
            if not linked:
                # Older writers logged the piece immediately before the scan attempt.
                preceding = [e for e in candidates if not (e.metadata_json or {}).get('scan_attempt_id')
                    and row.created_at - timedelta(seconds=5) <= e.timestamp <= row.created_at]
                linked = sorted(preceding, key=lambda e: (e.timestamp, e.id), reverse=True)[:1]
            for mirror in linked:
                _delete_piece_event(db, mirror)
    if isinstance(row, StockMovement):
        # Preserve the physical inventory records; detach their deleted movement.
        for attribute in (WarehouseItem.source_movement_id, WarehouseItem.exit_movement_id):
            db.query(WarehouseItem).filter(attribute == row.id).update(
                {attribute: None}, synchronize_session='fetch')
    if isinstance(row, PieceScanEvent):
        _delete_piece_event(db, row)
    else:
        db.delete(row)
    # The snapshot is a column on the deleted record: no orphan report copy remains.
    db.flush()
