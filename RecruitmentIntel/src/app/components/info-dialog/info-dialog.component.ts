import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatExpansionModule } from '@angular/material/expansion';

/** One step in a workflow diagram. */
export interface FlowStep {
  /** Material icon name shown in the round badge. */
  icon: string;
  /** Optional color override for the badge (defaults to grey). */
  color?: string;
  /** Step heading (short). */
  title: string;
  /** Optional one-line summary under the title. */
  subtitle?: string;
  /** Optional bullet list of intricacies / branches / fallbacks. */
  bullets?: string[];
  /** Set true to render this step as a "branch" off the main flow (indented + dashed border). */
  branch?: boolean;
}

export interface InfoDialogData {
  title: string;
  /** One-line elevator pitch shown under the title. */
  intro?: string;
  /** Section blocks — each gets its own collapsible group. */
  sections: { heading: string; description?: string; steps: FlowStep[] }[];
  /** Optional raw "key concepts" footer notes. */
  notes?: string[];
}

@Component({
  selector: 'app-info-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule, MatIconModule, MatExpansionModule],
  template: `
    <h2 mat-dialog-title>
      <mat-icon class="title-icon">help_outline</mat-icon>
      {{ data.title }}
    </h2>
    <mat-dialog-content class="info-content">
      @if (data.intro) {
        <p class="intro">{{ data.intro }}</p>
      }

      @for (section of data.sections; track section.heading; let sIdx = $index) {
        <mat-expansion-panel [expanded]="sIdx === 0" class="section-panel">
          <mat-expansion-panel-header>
            <mat-panel-title>{{ section.heading }}</mat-panel-title>
          </mat-expansion-panel-header>

          @if (section.description) {
            <p class="section-desc">{{ section.description }}</p>
          }

          <div class="flow">
            @for (step of section.steps; track $index; let last = $last) {
              <div class="flow-step" [class.branch]="step.branch">
                <div class="flow-badge" [style.background]="step.color || '#1976d2'">
                  <mat-icon>{{ step.icon }}</mat-icon>
                </div>
                <div class="flow-body">
                  <div class="flow-title">{{ step.title }}</div>
                  @if (step.subtitle) {
                    <div class="flow-subtitle">{{ step.subtitle }}</div>
                  }
                  @if (step.bullets && step.bullets.length > 0) {
                    <ul class="flow-bullets">
                      @for (b of step.bullets; track $index) {
                        <li>{{ b }}</li>
                      }
                    </ul>
                  }
                </div>
              </div>
              @if (!last) {
                <div class="flow-arrow">↓</div>
              }
            }
          </div>
        </mat-expansion-panel>
      }

      @if (data.notes && data.notes.length > 0) {
        <div class="notes">
          <h3>Key concepts</h3>
          <ul>
            @for (n of data.notes; track $index) {
              <li>{{ n }}</li>
            }
          </ul>
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-raised-button color="primary" (click)="ref.close()">
        <mat-icon>close</mat-icon> Close
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
    .title-icon {
      vertical-align: middle;
      margin-right: 6px;
      color: #1976d2;
    }
    .info-content {
      max-width: 820px;
      max-height: 75vh;
    }
    .intro {
      color: rgba(0, 0, 0, 0.7);
      font-size: 14px;
      margin: 0 0 16px;
    }
    .section-panel { margin-bottom: 8px; }
    .section-desc {
      color: rgba(0, 0, 0, 0.6);
      font-size: 13px;
      margin: 4px 0 12px;
    }
    .flow {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .flow-step {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 10px 12px;
      background: #fafafa;
      border-radius: 8px;
      border: 1px solid #e0e0e0;
    }
    .flow-step.branch {
      margin-left: 32px;
      background: #fff;
      border-style: dashed;
      border-color: #bdbdbd;
    }
    .flow-badge {
      flex: 0 0 36px;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      mat-icon { font-size: 20px; width: 20px; height: 20px; }
    }
    .flow-body { flex: 1; min-width: 0; }
    .flow-title {
      font-weight: 600;
      font-size: 14px;
      color: rgba(0, 0, 0, 0.85);
    }
    .flow-subtitle {
      font-size: 12px;
      color: rgba(0, 0, 0, 0.6);
      margin-top: 2px;
    }
    .flow-bullets {
      margin: 6px 0 0;
      padding-left: 18px;
      font-size: 12px;
      color: rgba(0, 0, 0, 0.7);
      li { margin: 2px 0; }
    }
    .flow-arrow {
      text-align: center;
      color: #1976d2;
      font-size: 18px;
      line-height: 1;
      padding: 2px 0;
    }
    .notes {
      margin-top: 16px;
      padding: 12px 16px;
      background: #fff8e1;
      border-left: 4px solid #ffa000;
      border-radius: 4px;
      h3 {
        margin: 0 0 8px;
        font-size: 14px;
        color: #e65100;
      }
      ul {
        margin: 0;
        padding-left: 20px;
        font-size: 13px;
        color: rgba(0, 0, 0, 0.75);
        li { margin: 3px 0; }
      }
    }
  `]
})
export class InfoDialogComponent {
  constructor(
    public ref: MatDialogRef<InfoDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: InfoDialogData,
  ) {}
}
