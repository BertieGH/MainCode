using AutoMapper;
using Survey.Core.DTOs.Common;
using Survey.Core.DTOs.User;
using Survey.Core.Entities;
using Survey.Core.Enums;
using Survey.Core.Exceptions;
using Survey.Core.Interfaces;

namespace Survey.Application.Services;

public class UserService : IUserService
{
    private readonly IUserRepository _userRepository;
    private readonly IUnitOfWork _unitOfWork;
    private readonly IMapper _mapper;

    public UserService(
        IUserRepository userRepository,
        IUnitOfWork unitOfWork,
        IMapper mapper)
    {
        _userRepository = userRepository;
        _unitOfWork = unitOfWork;
        _mapper = mapper;
    }

    public async Task<PagedResult<UserDto>> GetAllUsersAsync(int pageNumber, int pageSize)
    {
        var users = await _userRepository.GetUsersPagedAsync(pageNumber, pageSize);
        var totalCount = await _userRepository.GetTotalUsersCountAsync();

        var userDtos = _mapper.Map<List<UserDto>>(users);

        return new PagedResult<UserDto>
        {
            Items = userDtos,
            TotalCount = totalCount,
            PageNumber = pageNumber,
            PageSize = pageSize
        };
    }

    public async Task<UserDto?> GetUserByIdAsync(int id)
    {
        var user = await _userRepository.GetByIdAsync(id);
        if (user == null || user.IsDeleted)
            return null;

        return _mapper.Map<UserDto>(user);
    }

    public async Task<UserDto> CreateUserAsync(CreateUserDto dto)
    {
        var existingByUsername = await _userRepository.GetByUsernameAsync(dto.Username);
        if (existingByUsername != null)
            throw new BusinessRuleException("Username is already taken");

        var existingByEmail = await _userRepository.GetByEmailAsync(dto.Email);
        if (existingByEmail != null)
            throw new BusinessRuleException("Email is already registered");

        if (!Enum.TryParse<UserRole>(dto.Role, out var role))
            throw new BusinessRuleException($"Invalid role: {dto.Role}");

        var user = new User
        {
            Username = dto.Username,
            Email = dto.Email,
            PasswordHash = BCrypt.Net.BCrypt.HashPassword(dto.Password),
            Role = role,
            IsActive = true,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow
        };

        await _userRepository.AddAsync(user);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<UserDto>(user);
    }

    public async Task<UserDto> UpdateUserAsync(int id, UpdateUserDto dto)
    {
        var user = await _userRepository.GetByIdAsync(id);
        if (user == null || user.IsDeleted)
            throw new NotFoundException("User", id);

        // Check username uniqueness if changed
        if (user.Username != dto.Username)
        {
            var existingByUsername = await _userRepository.GetByUsernameAsync(dto.Username);
            if (existingByUsername != null)
                throw new BusinessRuleException("Username is already taken");
        }

        // Check email uniqueness if changed
        if (user.Email != dto.Email)
        {
            var existingByEmail = await _userRepository.GetByEmailAsync(dto.Email);
            if (existingByEmail != null)
                throw new BusinessRuleException("Email is already registered");
        }

        user.Username = dto.Username;
        user.Email = dto.Email;
        user.UpdatedAt = DateTime.UtcNow;

        if (!string.IsNullOrEmpty(dto.Role))
        {
            if (!Enum.TryParse<UserRole>(dto.Role, out var role))
                throw new BusinessRuleException($"Invalid role: {dto.Role}");
            user.Role = role;
        }

        await _userRepository.UpdateAsync(user);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<UserDto>(user);
    }

    public async Task DeleteUserAsync(int id)
    {
        var user = await _userRepository.GetByIdAsync(id);
        if (user == null || user.IsDeleted)
            throw new NotFoundException("User", id);

        user.IsDeleted = true;
        user.UpdatedAt = DateTime.UtcNow;

        await _userRepository.UpdateAsync(user);
        await _unitOfWork.SaveChangesAsync();
    }

    public async Task<UserDto> ToggleActiveAsync(int id)
    {
        var user = await _userRepository.GetByIdAsync(id);
        if (user == null || user.IsDeleted)
            throw new NotFoundException("User", id);

        user.IsActive = !user.IsActive;
        user.UpdatedAt = DateTime.UtcNow;

        await _userRepository.UpdateAsync(user);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<UserDto>(user);
    }

    public async Task<UserDto> ChangeRoleAsync(int id, string role)
    {
        var user = await _userRepository.GetByIdAsync(id);
        if (user == null || user.IsDeleted)
            throw new NotFoundException("User", id);

        if (!Enum.TryParse<UserRole>(role, out var userRole))
            throw new BusinessRuleException($"Invalid role: {role}");

        user.Role = userRole;
        user.UpdatedAt = DateTime.UtcNow;

        await _userRepository.UpdateAsync(user);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<UserDto>(user);
    }

    public async Task ChangePasswordAsync(int id, ChangePasswordDto dto)
    {
        var user = await _userRepository.GetByIdAsync(id);
        if (user == null || user.IsDeleted)
            throw new NotFoundException("User", id);

        if (!BCrypt.Net.BCrypt.Verify(dto.CurrentPassword, user.PasswordHash))
            throw new BusinessRuleException("Current password is incorrect");

        user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(dto.NewPassword);
        user.UpdatedAt = DateTime.UtcNow;

        await _userRepository.UpdateAsync(user);
        await _unitOfWork.SaveChangesAsync();
    }
}
