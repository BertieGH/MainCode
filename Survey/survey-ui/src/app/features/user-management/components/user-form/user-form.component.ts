import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, ActivatedRoute, RouterModule } from '@angular/router';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { UserService } from '../../services/user.service';
import { UserRole } from '../../../../core/models/user.model';
import { PageTitleService } from '../../../../core/services/page-title.service';

@Component({
  selector: 'app-user-form',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    MatProgressSpinnerModule
  ],
  templateUrl: './user-form.component.html',
  styleUrls: ['./user-form.component.scss']
})
export class UserFormComponent implements OnInit {
  userForm!: FormGroup;
  roles = Object.values(UserRole);
  isEditMode = false;
  userId?: number;
  formLoading = false;
  saving = false;
  error: string | null = null;

  constructor(
    private fb: FormBuilder,
    private userService: UserService,
    private router: Router,
    private route: ActivatedRoute,
    private pageTitle: PageTitleService
  ) {}

  ngOnInit(): void {
    this.route.params.subscribe(params => {
      if (params['id']) {
        this.isEditMode = true;
        this.userId = +params['id'];
        this.initForm();
        this.loadUser(this.userId);
      } else {
        this.initForm();
      }
    });

    this.pageTitle.setTitle(this.isEditMode ? 'Edit User' : 'Create User', 'User Management');
  }

  private initForm(): void {
    if (this.isEditMode) {
      this.userForm = this.fb.group({
        username: ['', [Validators.required, Validators.minLength(3)]],
        email: ['', [Validators.required, Validators.email]],
        role: [UserRole.User, Validators.required]
      });
    } else {
      this.userForm = this.fb.group({
        username: ['', [Validators.required, Validators.minLength(3)]],
        email: ['', [Validators.required, Validators.email]],
        password: ['', [Validators.required, Validators.minLength(6)]],
        role: [UserRole.User, Validators.required]
      });
    }
  }

  private loadUser(id: number): void {
    this.formLoading = true;
    this.userService.getUserById(id).subscribe({
      next: (user) => {
        this.userForm.patchValue({
          username: user.username,
          email: user.email,
          role: user.role
        });
        this.formLoading = false;
      },
      error: (err) => {
        this.error = err.error?.message || 'Failed to load user';
        this.formLoading = false;
      }
    });
  }

  onSubmit(): void {
    if (this.userForm.invalid) return;

    this.saving = true;
    this.error = null;

    const request = this.isEditMode && this.userId
      ? this.userService.updateUser(this.userId, this.userForm.value)
      : this.userService.createUser(this.userForm.value);

    request.subscribe({
      next: () => {
        this.router.navigate(['/users']);
      },
      error: (err) => {
        this.error = err.error?.message || 'Failed to save user';
        this.saving = false;
      }
    });
  }
}
