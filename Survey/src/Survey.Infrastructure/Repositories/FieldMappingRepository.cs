using Microsoft.EntityFrameworkCore;
using Survey.Core.Entities;
using Survey.Core.Interfaces;
using Survey.Infrastructure.Data;

namespace Survey.Infrastructure.Repositories;

public class FieldMappingRepository : Repository<FieldMapping>, IFieldMappingRepository
{
    public FieldMappingRepository(SurveyDbContext context) : base(context)
    {
    }

    public async Task<IEnumerable<FieldMapping>> GetAllMappingsAsync()
    {
        return await _dbSet
            .OrderBy(fm => fm.CrmFieldName)
            .ToListAsync();
    }

    public async Task<FieldMapping?> GetMappingByIdAsync(int id)
    {
        return await _dbSet.FirstOrDefaultAsync(fm => fm.Id == id);
    }
}
